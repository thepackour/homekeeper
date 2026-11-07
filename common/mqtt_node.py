"""홈키퍼 공통 MQTT 모듈.

각 노드는 이 모듈의 Node 하나만 만들고, 자기 토픽에 무엇을 할지만 적는다.
접속, LWT, 살아 있음 신호, JSON과 "t", QoS/retain 규칙, 예비 브로커 전환은
모두 여기서 처리한다. 규약은 docs/mqtt.md 를 따른다.

사용 예:
    from common.mqtt_node import Node

    node = Node("living")

    @node.on("home/cmd/living/camera")
    def on_camera(msg, topic):
        print("카메라 켜기", msg["sec"])

    node.publish("home/living/count", {"count": 2})
    node.run()          # Ctrl+C 로 종료
"""

import json
import logging
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

log = logging.getLogger("homekeeper.mqtt")

COMMON_DIR = Path(__file__).resolve().parent
CONFIG_PATH = COMMON_DIR / "config.json"
SECRETS_PATH = COMMON_DIR / "secrets.json"  # git에 올리지 않음

# 규약: retain 은 이 두 접두어만
RETAIN_PREFIXES = ("home/state/", "home/status/")
# 규약: 살아 있음 신호만 QoS 0, 나머지(상태·경보·명령)는 1
QOS0_PREFIXES = ("home/status/",)


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_password(name, path=SECRETS_PATH):
    """secrets.json 에서 노드 비밀번호를 읽는다. 파일이 없으면 None(인증 없이 접속)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get(name)
    except FileNotFoundError:
        return None


def default_qos(topic):
    return 0 if topic.startswith(QOS0_PREFIXES) else 1


def default_retain(topic):
    return topic.startswith(RETAIN_PREFIXES)


class Node:
    """홈키퍼 노드 하나의 MQTT 연결.

    name: door / living / hub / wallpad / phone (config.json 의 계정 이름)
    """

    def __init__(self, name, config=None):
        self.name = name
        self.config = config or load_config()
        self.brokers = self.config["brokers"]          # [주, 예비]
        self.failover_sec = self.config.get("failover_sec", 3)
        self.heartbeat_sec = self.config.get("heartbeat_sec", 1)
        self.status_topic = f"home/status/{name}"

        self._handlers = []          # (토픽 필터, 함수)
        self._lock = threading.Lock()
        self._switch_lock = threading.Lock()
        self._connected = threading.Event()
        self._lost_at = time.monotonic()   # 처음엔 '끊긴 상태'에서 시작
        self._stop = threading.Event()
        self.broker_index = 0        # 0 = 주(hub), 1 = 예비(door)
        self.on_broker_change = None  # 전환 시 알림을 받고 싶으면 함수 지정: f(index, broker)

        self._client = self._make_client()

    # ---------- 노드가 쓰는 API ----------

    def on(self, topic_filter):
        """구독 데코레이터. 와일드카드(+, #) 사용 가능. 함수는 (msg, topic) 을 받는다."""
        def deco(func):
            with self._lock:
                self._handlers.append((topic_filter, func))
            if self._connected.is_set():
                self._client.subscribe(topic_filter, qos=1)
            return func
        return deco

    def publish(self, topic, payload=None, qos=None, retain=None):
        """dict 를 JSON 으로 보낸다. "t"(보낸 시각, 초)는 자동으로 붙는다.

        QoS 와 retain 은 규약에 맞춰 토픽으로 자동 결정된다.
        규약에 없는 retain 을 요청하면 막는다.
        """
        if retain and not default_retain(topic):
            raise ValueError(f"retain 은 home/state/, home/status/ 에만 쓸 수 있습니다: {topic}")
        body = dict(payload or {})
        body.setdefault("t", round(time.time(), 3))
        qos = default_qos(topic) if qos is None else qos
        retain = default_retain(topic) if retain is None else retain
        info = self._client.publish(topic, json.dumps(body, ensure_ascii=False), qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning("발행 실패(%s): %s", mqtt.error_string(info.rc), topic)
        return info

    @property
    def connected(self):
        return self._connected.is_set()

    @property
    def broker(self):
        return self.brokers[self.broker_index]

    def start(self):
        """백그라운드로 시작한다. 메인 루프(카메라 처리 등)를 따로 돌릴 때 쓴다."""
        self._connect(self.broker_index)
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._watch_loop, daemon=True).start()

    def run(self):
        """start() 후 Ctrl+C 까지 대기한다."""
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        self._stop.set()
        try:
            # 정상 종료도 '죽음'으로 알린다(LWT 는 비정상 종료에만 나가므로 직접 보냄)
            self._client.publish(self.status_topic, json.dumps({"alive": 0, "t": round(time.time(), 3)}),
                                 qos=1, retain=True).wait_for_publish(1)
        except Exception:
            pass
        self._client.disconnect()
        self._client.loop_stop()

    def switch_broker(self, index):
        """브로커를 수동으로 바꾼다. 허브 복구 후 주 브로커로 되돌릴 때 사용."""
        with self._switch_lock:
            if index == self.broker_index and self._connected.is_set():
                return
            self._client.loop_stop()
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = self._make_client()
            self._connect(index)
        if self.on_broker_change:
            self.on_broker_change(index, self.broker)

    # ---------- 내부 ----------

    def _make_client(self):
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"homekeeper-{self.name}", clean_session=True)
        password = load_password(self.name)
        if password is not None:
            c.username_pw_set(self.name, password)
        c.will_set(self.status_topic, json.dumps({"alive": 0}), qos=1, retain=True)
        c.reconnect_delay_set(min_delay=1, max_delay=2)
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        return c

    def _connect(self, index):
        self.broker_index = index
        b = self.brokers[index]
        log.info("[%s] 브로커 접속 시도: %s:%s", self.name, b["host"], b["port"])
        try:
            # connect_async: 상대가 꺼져 있어도 멈추지 않고 백그라운드에서 재시도
            self._client.connect_async(b["host"], b["port"], keepalive=5)
        except Exception as e:  # 이름 해석 실패 등
            log.warning("[%s] 접속 준비 실패: %s", self.name, e)
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("[%s] 접속 거부: %s", self.name, reason_code)
            return
        log.info("[%s] 접속됨: %s", self.name, self.broker["host"])
        self._connected.set()
        with self._lock:
            for topic_filter, _ in self._handlers:
                client.subscribe(topic_filter, qos=1)
        self.publish(self.status_topic, {"alive": 1})

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if self._connected.is_set():
            log.warning("[%s] 연결 끊김: %s", self.name, reason_code)
            self._lost_at = time.monotonic()
        self._connected.clear()

    def _on_message(self, client, userdata, message):
        try:
            text = message.payload.decode("utf-8")
            msg = json.loads(text) if text else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("[%s] JSON 아님, 무시: %s", self.name, message.topic)
            return
        with self._lock:
            handlers = [f for flt, f in self._handlers if mqtt.topic_matches_sub(flt, message.topic)]
        for func in handlers:
            try:
                func(msg, message.topic)
            except Exception:
                log.exception("[%s] 핸들러 오류: %s", self.name, message.topic)

    def _heartbeat_loop(self):
        while not self._stop.wait(self.heartbeat_sec):
            if self._connected.is_set():
                self.publish(self.status_topic, {"alive": 1})

    def _watch_loop(self):
        """주 브로커가 failover_sec 이상 끊기면 예비로 넘어간다.

        예비로 넘어간 뒤에는 자동으로 돌아가지 않는다(노드마다 제각각 돌아가
        브로커가 둘로 갈라지는 것을 막기 위해). 되돌릴 때는 switch_broker(0).
        """
        while not self._stop.wait(0.5):
            if self._connected.is_set() or self.broker_index != 0 or len(self.brokers) < 2:
                continue
            if time.monotonic() - self._lost_at >= self.failover_sec:
                log.warning("[%s] 주 브로커 %s초 끊김 → 예비 브로커로 전환", self.name, self.failover_sec)
                self.switch_broker(1)
