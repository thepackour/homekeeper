#!/usr/bin/env python3
"""홈키파 ③ 홈 허브 판단 프로그램.

- 꼬리물기: 문이 열리면 거실 카메라를 켜고, 인증 횟수와 거실 진입 인원을 비교
- 의심 단계 0~3, 모드(외출 준비 30초 포함), 집 안 인원을 home/state/ 에 retain 발행
- 노드 끊김 감지, 경보 해제, 출입 허락 기록
- 아두이노 C(경보 LED, 부저, 도트매트릭스)에 단계 전송, 폰 알림(ntfy)
- 기록: hub/homekeeper.db (SQLite, git에 안 올림)

실행 (레포 맨 위에서): python3 hub/hub.py
규약: docs/mqtt.md / MQTT 접속은 common/mqtt_node.py 의 Node 가 처리
"""
import json
import logging
import sqlite3
import sys
import threading
import time
import urllib.request
from pathlib import Path

HUB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HUB_DIR.parent))          # 레포 맨 위 (common 모듈)
from common.mqtt_node import Node  # noqa: E402

CFG = json.load(open(HUB_DIR / "config.json", encoding="utf-8"))
try:  # ntfy 토픽 (git에 안 올림). 없으면 폰 알림은 로그로만
    NTFY_TOPIC = json.load(open(HUB_DIR / "hub_secret.json", encoding="utf-8")).get("ntfy_topic")
except FileNotFoundError:
    NTFY_TOPIC = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("hub")


def now():
    return time.time()


# ------------------------------------------------------------------ 상태
S = {
    "mode": "home",        # home / away / sleep (규약)
    "until": 0,            # away 이면서 until > now 이면 외출 준비 중(30초)
    "occupancy": 0,
    "suspicion": 0, "reason": "",
    "loiter_until": 0,
    "judge": "hub",
}
win = None              # 꼬리물기 판단 창 {"auth": n, "deadline": t}
last_auth_t = 0
away_open_at = 0        # 외출 중 인증 없이 문 열린 시각
lost_nodes = set()
restored = False
lock = threading.RLock()

# ------------------------------------------------------------------ 기록
db = sqlite3.connect(HUB_DIR / "homekeeper.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS events (t INTEGER, kind TEXT, detail TEXT)")
db.commit()


def record(kind, detail):
    with lock:
        db.execute("INSERT INTO events VALUES (?,?,?)",
                   (int(now()), kind, json.dumps(detail, ensure_ascii=False)))
        db.commit()


# ------------------------------------------------------------------ 아두이노 C
class Board:
    """아두이노 C 시리얼. 뽑혔다 다시 꽂혀도 5초마다 다시 연결 시도"""

    def __init__(self, port):
        self.port, self.ser, self.last_try, self.last_line = port, None, 0, None
        self.open(first=True)

    def open(self, first=False):
        self.last_try = time.time()
        try:
            import serial
            self.ser = serial.Serial(self.port, 9600, timeout=1)
            time.sleep(2)  # 아두이노 리셋 대기
            log.info("아두이노 C 연결: %s", self.port)
            if self.last_line:          # 다시 꽂혔으면 마지막 단계 다시 보냄
                self.ser.write((self.last_line + "\n").encode())
        except Exception as e:
            self.ser = None
            if first:
                log.warning("아두이노 C 없음, 출력은 로그로만 (%s)", e)

    def check(self):
        if self.ser is None and time.time() - self.last_try > 5:
            self.open()

    def send(self, line):
        self.last_line = line
        log.info("  → 아두이노 C: %s", line)
        if self.ser:
            try:
                self.ser.write((line + "\n").encode())
            except Exception as e:
                log.warning("아두이노 C 끊김 (%s), 다시 연결 시도", e)
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None


board = Board(CFG["serial"])


# ------------------------------------------------------------------ 폰 알림 (ntfy)
def notify(title, message, priority=3, tags=None):
    if not NTFY_TOPIC:
        log.info("  → 폰 알림(토픽 없음, 로그만): %s / %s", title, message)
        return
    body = {"topic": NTFY_TOPIC, "title": title, "message": message,
            "priority": priority, "tags": tags or []}

    def _send():
        try:
            req = urllib.request.Request(CFG["ntfy_url"].rstrip("/"), data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=5).read()
            log.info("  → 폰 알림: %s / %s", title, message)
        except Exception as e:
            log.warning("  → 폰 알림 실패 (%s): %s", e, title)

    threading.Thread(target=_send, daemon=True).start()


# ------------------------------------------------------------------ 발행
node = Node("hub")


def pub_state():
    node.publish("home/state/mode", {"mode": S["mode"], "until": int(S["until"])})
    node.publish("home/state/occupancy", {"n": S["occupancy"]})
    node.publish("home/state/suspicion", {"level": S["suspicion"], "reason": S["reason"]})
    node.publish("home/state/risk", {"away": int(S["mode"] == "away"), "loiter_until": int(S["loiter_until"])})
    node.publish("home/state/judge", {"node": S["judge"]})


def set_suspicion(level, reason):
    """의심 단계는 올리기만 함. 내릴 때는 clear_suspicion."""
    if level > S["suspicion"]:
        S["suspicion"], S["reason"] = level, reason
        log.info("의심 단계 %d (%s)", level, reason)
        board.send(f"S{level}")
        pub_state()


def clear_suspicion(reason=None):
    """reason이 지금 원인과 같을 때만 0으로. 경보(3)는 해제 명령으로만 내림."""
    if S["suspicion"] < 3 and (reason is None or S["reason"] == reason):
        S["suspicion"], S["reason"] = 0, ""
        board.send("S0")
        pub_state()


ALERT_TITLE = {"tailgate": "침입 의심 (꼬리물기)", "intrusion": "외출 중 침입"}


def raise_alert(kind, message):
    S["suspicion"], S["reason"] = 3, kind
    log.warning("경보 3: %s (%s)", kind, message)
    board.send("S3")
    node.publish("home/alert", {"level": 3, "type": kind})
    node.publish("home/cmd/living/camera", {"on": 1, "sec": 10})   # 경보 촬영
    pub_state()
    notify(ALERT_TITLE.get(kind, "경보"), message, priority=5, tags=["rotating_light"])
    record("alert", {"level": 3, "type": kind, "msg": message})


# ------------------------------------------------------------------ 이벤트 처리
def on_door_auth(p):
    global win, last_auth_t, away_open_at
    record("auth", p)
    if p.get("result") != "ok":
        return
    last_auth_t = now()
    away_open_at = 0
    if S["mode"] == "away":
        S["mode"], S["until"] = "home", 0
        log.info("인증 통과 → 재택 모드로 전환")
        clear_suspicion("away_open")
        pub_state()
    deadline = now() + CFG["window_sec"]
    if win is None:
        win = {"auth": 1, "deadline": deadline}
    else:
        win["auth"] += 1
        win["deadline"] = deadline
    log.info("인증 통과 (창 안 인증 %d회)", win["auth"])


def on_door_open(p):
    global away_open_at
    record("door", p)
    if p.get("state") != "open":
        return
    by = p.get("by")
    if by in ("auth", "approve"):
        # 들어오는 사람 세기: 거실 카메라 켜기
        node.publish("home/cmd/living/camera", {"on": 1, "sec": CFG["camera_sec"]})
        if by == "approve" and win is None:
            # 원격 허락으로 열림: 인증 1회로 보고 판단 창 열기
            on_door_auth({"result": "ok", "method": "approve"})
    elif S["mode"] == "away" and now() >= S["until"]:
        away_open_at = now()   # 외출 중 인증 없이 열림 → 30초 안에 인증 없으면 경고


def on_living_count(p):
    global win
    n = int(p.get("count", 0))
    if win is None:
        log.info("거실 인원 %d (열린 판단 창 없음, 무시)", n)
        return
    auth = win["auth"]
    win = None
    record("count", {"auth": auth, "count": n})
    if n > auth:
        raise_alert("tailgate", f"인증 {auth}회, 진입 {n}명")
    else:
        S["occupancy"] += n
        log.info("정상: 인증 %d, 진입 %d → 집 안 %d명", auth, n, S["occupancy"])
        pub_state()


def check_window():
    """거실 결과가 안 오면 인증 수만큼만 더하고 의심 단계 1"""
    global win
    if win and now() > win["deadline"]:
        auth = win["auth"]
        win = None
        S["occupancy"] += auth
        log.warning("거실 인원 응답 없음 → 인증 %d명만 반영", auth)
        record("count_timeout", {"auth": auth})
        set_suspicion(1, "living_timeout")
        pub_state()


def check_away_open():
    global away_open_at
    if away_open_at and now() - away_open_at > CFG["away_open_sec"]:
        away_open_at = 0
        record("away_open", {})
        set_suspicion(2, "away_open")
        notify("외출 중 문 열림", "문이 열린 뒤 30초 동안 인증이 없었습니다", priority=4, tags=["warning"])


def on_door_exit(p):
    S["occupancy"] = max(0, S["occupancy"] - 1)
    record("exit", p)
    log.info("나감 → 집 안 %d명", S["occupancy"])
    pub_state()
    if S["occupancy"] == 0 and S["mode"] == "home":
        notify("집이 비었습니다", "외출 모드로 바꾸려면 월패드를 확인하세요", priority=2)


def on_door_loiter(p):
    st = p.get("state")
    record("loiter", p)
    if st == "start":
        S["loiter_until"] = now() + CFG["loiter_keep_sec"]
        set_suspicion(1, "loiter")
        pub_state()
    elif st == "over30":
        set_suspicion(2, "loiter")
        notify("문 앞 서성임", "30초 넘게 문 앞에 사람이 있습니다", priority=4, tags=["eyes"])
    elif st == "end":
        clear_suspicion("loiter")


def on_door_pwfail(p):
    record("pwfail", p)
    if int(p.get("count", 0)) >= 3:
        set_suspicion(1, "pwfail")


def on_door_duress(p):
    record("duress", p)
    notify("비상 번호 입력", "현관에서 비상 번호가 입력됐습니다", priority=5, tags=["sos"])


def on_living_motion(p):
    if p.get("state") != 1:
        return
    record("motion", p)
    if S["mode"] == "away" and now() >= S["until"] and now() - last_auth_t > CFG["motion_after_auth_sec"]:
        raise_alert("intrusion", "외출 중 인증 기록 없이 거실 움직임")


def on_cmd_mode(p):
    m = p.get("mode")
    record("cmd_mode", p)
    if m == "away":
        S["mode"], S["until"] = "away", now() + CFG["arming_sec"]
        log.info("외출 준비 %d초", CFG["arming_sec"])
    elif m in ("home", "sleep"):
        S["mode"], S["until"] = m, 0
    pub_state()


def on_cmd_dismiss(p):
    global away_open_at
    record("dismiss", p)
    away_open_at = 0
    S["suspicion"], S["reason"] = 0, ""
    board.send("S0")
    log.info("경보 해제 (%s)", p.get("by", "?"))
    pub_state()


def on_cmd_approve(p):
    """허락, 거절은 현관이 직접 받음. 허브는 기록만"""
    record("approve", p)
    log.info("출입 %s", "허락" if p.get("ok") else "거절")


def on_status(p, topic):
    nd = topic.rsplit("/", 1)[-1]
    if nd not in CFG["watch_nodes"]:
        return
    alive = p.get("alive")
    if alive == 0 and nd not in lost_nodes:
        lost_nodes.add(nd)
        record("node_lost", {"node": nd})
        set_suspicion(1, f"{nd}_lost")
        notify("노드 응답 없음", f"{nd} 연결이 끊겼습니다", priority=4, tags=["warning"])
    elif alive == 1 and nd in lost_nodes:
        lost_nodes.discard(nd)
        record("node_back", {"node": nd})
        log.info("%s 다시 연결", nd)
        clear_suspicion(f"{nd}_lost")


def restore(p, topic):
    """허브 재시작 시 브로커에 남은 retain 상태로 복구 (시작 후 2초 동안만)"""
    key = topic.rsplit("/", 1)[-1]
    if key == "mode":
        S["mode"], S["until"] = p.get("mode", "home"), p.get("until", 0)
    elif key == "occupancy":
        S["occupancy"] = p.get("n", 0)
    elif key == "risk":
        S["loiter_until"] = p.get("loiter_until", 0)
    elif key == "suspicion":
        S["suspicion"], S["reason"] = p.get("level", 0), p.get("reason", "")


HANDLERS = {
    "home/door/auth": on_door_auth,
    "home/door/open": on_door_open,
    "home/door/exit": on_door_exit,
    "home/door/loiter": on_door_loiter,
    "home/door/pwfail": on_door_pwfail,
    "home/door/duress": on_door_duress,
    "home/living/count": on_living_count,
    "home/living/motion": on_living_motion,
    "home/cmd/mode": on_cmd_mode,
    "home/cmd/dismiss": on_cmd_dismiss,
    "home/cmd/approve": on_cmd_approve,
}


def make_handler(func, topic):
    def h(msg, _topic):
        with lock:
            log.info("← %s %s", topic, msg)
            func(msg)
    return h


for _topic, _func in HANDLERS.items():
    node.on(_topic)(make_handler(_func, _topic))


@node.on("home/status/+")
def _status(msg, topic):
    with lock:
        on_status(msg, topic)


@node.on("home/state/+")
def _state(msg, topic):
    with lock:
        if not restored:
            restore(msg, topic)


def main():
    global restored
    log.info("홈 허브 시작")
    node.start()
    time.sleep(2)              # retain 상태 받을 시간
    with lock:
        restored = True
        S["judge"] = "hub"
        board.send(f"S{S['suspicion']}")
        pub_state()
    try:
        while True:
            with lock:
                check_window()
                check_away_open()
            board.check()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == "__main__":
    main()
