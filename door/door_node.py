"""현관 메인 프로그램.

카드 → 얼굴 확인 → (위험 점수에 따라) 리모컨 비밀번호 → (점수가 높으면) 월패드 허락 → 문 열림.
월패드나 폰이 보내는 출입 허락(home/cmd/approve {"ok":1})은 현관이 직접 듣고 문을 연다. 허브는 기록만 한다.
인증 결과, 문 열림, 나가기 버튼, 서성임, 방문자 사진을 MQTT로 보낸다.
규약은 docs/mqtt.md, 위험 점수 기준은 제안서 7.3을 따른다.
문 열림은 서보(SG90)가 걸쇠를 돌리고, LCD 글자와 부저로도 알린다. 5초 뒤 다시 잠근다.

Pi:     python3 door_node.py
노트북: python door_node.py --fake --no-camera --broker localhost
"""
import argparse
import logging
import sys
import time
from pathlib import Path
from time import monotonic

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR.parent))  # 저장소 맨 위에서 common/ 을 찾는다

from common.mqtt_node import Node, load_config  # noqa: E402

from door_setup import check_password, load_data  # noqa: E402
from loiter import LoiterWatch  # noqa: E402
from uno_link import load_ir_labels  # noqa: E402

log = logging.getLogger("door")

# 시간 (초)
FACE_WAIT_SEC = 3          # 카드를 댄 뒤 얼굴을 기다리는 시간 (등록된 얼굴이 보이면 바로 넘어감)
FACE_BEFORE_SEC = 3        # 카드를 대기 직전에 본 얼굴도 인정
PASSWORD_TIMEOUT_SEC = 20  # 리모컨을 이만큼 안 누르면 취소
APPROVE_TIMEOUT_SEC = 60   # 월패드 허락을 기다리는 시간
OPEN_SEC = 5               # 제안서: 개방 5초 후 자동 잠김
MESSAGE_SEC = 2            # "UNKNOWN CARD" 같은 안내를 보여 주는 시간
LOCKOUT_SEC = 30           # 비밀번호 3번 틀리면 이만큼 카드를 받지 않음
LOITER_MEMORY_SEC = 600    # 제안서: 10분 안에 서성임이 있었으면 +2

# 위험 점수 (제안서 7.3)
SCORE_NIGHT = 2            # 새벽 0~6시
SCORE_FACE = 2             # 얼굴 불일치, 미인식
SCORE_LOITER = 2           # 10분 안에 문 앞 서성임
SCORE_AWAY = 1             # 외출 모드
SCORE_PW_ERROR = 1         # 비밀번호 오류 1번마다
NEED_PASSWORD = 2          # 2~3점: 카드 + 비밀번호
NEED_APPROVE = 4           # 4점 이상: 카드 + 비밀번호 + 월패드 허락
ALARM_LEVEL = 3            # 이 의심 단계(전체 경보) 중에는 월패드 허락이 필요

MAX_PW_ERRORS = 3
MAX_PASSWORD_LEN = 8

# 소리 (주파수 Hz, 밀리초). 우노는 소리 나는 동안 멈추므로 짧게 쓴다.
KEY_BEEP = ((2093, 40),)
OK_BEEP = ((1568, 120),)
ERROR_BEEP = ((440, 300),)
OPEN_MELODY = ((1047, 100), (1319, 100), (1568, 160))
ALARM = ((880, 400), (660, 400), (880, 400), (660, 400))


class Door:
    def __init__(self, uno, node, faces, data, loiter):
        self.uno = uno
        self.node = node
        self.faces = faces
        self.data = data
        self.loiter = loiter
        self.labels = load_ir_labels()
        self.screen = ["", ""]
        self.state = "idle"       # idle / face / password / approve / open / message
        self.deadline = 0.0
        self.locked_until = 0.0
        self.pw_errors = 0        # 성공할 때까지 쌓이는 비밀번호 오류 횟수

        # 지금 진행 중인 인증
        self.name = None
        self.card_time = 0.0
        self.face = "none"
        self.score = 0
        self.method = "card"
        self.typed = ""

        # 허브와 월패드가 보내는 집 상태 (MQTT 스레드에서 값만 바꾼다)
        self.mode = "home"
        self.suspicion = 0
        self.loiter_until = 0.0
        self.loiter_cleared = 0.0  # 출입 성공으로 서성임 기록을 지운 시각 (time.time())
        self.approve_ok = None
        self.approve_at = 0.0
        self.approve_done = 0.0   # 메인 루프가 마지막으로 처리한 허락의 시각
        self.subscribe()

    # ---------- MQTT ----------

    def subscribe(self):
        node = self.node

        @node.on("home/state/mode")
        def on_mode(msg, topic):
            self.mode = msg.get("mode", self.mode)

        @node.on("home/state/suspicion")
        def on_suspicion(msg, topic):
            self.suspicion = int(msg.get("level") or 0)

        @node.on("home/state/risk")
        def on_risk(msg, topic):
            value = msg.get("loiter_until")
            self.loiter_until = float(value) if isinstance(value, (int, float)) else 0.0

        @node.on("home/cmd/approve")
        def on_approve(msg, topic):
            self.approve_ok = msg.get("ok")
            self.approve_at = monotonic()

    def publish(self, topic, payload=None):
        self.node.publish(topic, payload)
        if payload and "img" in payload:
            log.info("-> %s (photo %d KB)", topic, len(payload["img"]) // 1024)
        else:
            log.info("-> %s %s", topic, payload or "")

    # ---------- LCD, 부저 ----------

    def show(self, top, bottom=""):
        for line, text in enumerate((top, bottom)):
            text = text[:16]
            if self.screen[line] != text:  # 바뀐 줄만 보낸다
                self.uno.lcd(line, text)
                self.screen[line] = text

    def sound(self, notes):
        for frequency, milliseconds in notes:
            self.uno.beep(frequency, milliseconds)

    def message(self, now, top, bottom="", notes=None, seconds=MESSAGE_SEC):
        self.state, self.deadline = "message", now + seconds
        self.show(top, bottom)
        if notes:
            self.sound(notes)

    def with_risk(self, text):
        """LCD 첫 줄 끝에 위험 점수를 붙인다. 데모 때 왜 비밀번호를 묻는지 바로 보이게."""
        full = f"{text} RISK {self.score}"
        return full if len(full) <= 16 else f"{text} R{self.score}"

    def show_idle(self, now):
        top = "HOMEKEEPER" if self.node.connected else "HOMEKEEPER (OFF)"
        if now < self.locked_until:
            self.show(top, f"LOCKED {int(self.locked_until - now) + 1}S")
        else:
            self.show(top, "TAP CARD")

    # ---------- 우노 메시지 ----------

    def handle(self, line, now):
        if line == "READY":  # 우노가 다시 켜졌으면 화면을 다시 그린다
            self.screen = ["", ""]
        elif line.startswith("RC522:"):
            log.info("Card reader chip version %s", line[6:])
        elif line == "BTN":
            self.exit_button(now)
        elif line.startswith("CARD:"):
            self.card(line[5:], now)
        elif line.startswith("IR:"):
            self.remote(self.labels.get(line[3:]), now)
        elif line.startswith("DIST:"):
            try:
                self.distance(int(line[5:]), now)
            except ValueError:
                pass

    def exit_button(self, now):
        """나가기 버튼은 언제나 문을 연다 (제안서). 진행 중이던 인증은 취소된다."""
        log.info("Exit button")
        self.publish("home/door/exit")
        self.open_door(now, "exit", "GOODBYE")

    def card(self, uid, now):
        if self.state != "idle":
            return
        if now < self.locked_until:
            self.sound(ERROR_BEEP)
            return
        self.data = load_data()  # 등록을 바꿨으면 다시 켜지 않아도 반영
        name = self.data["cards"].get(uid)
        if name is None:
            log.info("Unknown card %s", uid)
            self.method, self.face, self.score = "card", "none", 0
            self.publish("home/door/auth", {"result": "fail", "method": "card"})
            self.message(now, "UNKNOWN CARD", "", ERROR_BEEP)
            return
        log.info("Card %s (%s)", uid, name)
        self.name, self.card_time = name, now
        self.method, self.typed, self.face = "card", "", "none"
        self.state, self.deadline = "face", now + FACE_WAIT_SEC
        self.show(f"HELLO {name.upper()}", "LOOK AT CAMERA")
        self.sound(OK_BEEP)

    def remote(self, key, now):
        if self.state != "password" or key is None:
            return
        self.deadline = now + PASSWORD_TIMEOUT_SEC
        if key == "CONFIRM":
            self.submit_password(now)
            return
        if key.isdigit() and len(self.typed) < MAX_PASSWORD_LEN:
            self.typed += key
        elif key == "DELETE":
            self.typed = self.typed[:-1]
        self.show(self.screen[0], "PW:" + "*" * len(self.typed))
        self.sound(KEY_BEEP)

    def distance(self, cm, now):
        if self.state != "idle":  # 인증 중이거나 문이 열려 있을 때는 서성임으로 세지 않는다
            self.loiter.hold(now)
            return
        event = self.loiter.update(cm, now)
        if event is None:
            return
        self.publish("home/door/loiter", {"state": event})
        if event == "start":
            self.send_visitor_photo()

    def send_visitor_photo(self):
        if self.faces is None:
            log.info("No camera, so no visitor photo")
            return
        image = self.faces.photo_base64()
        if image:
            self.publish("home/door/visitor", {"img": image})

    # ---------- 인증 단계 ----------

    def tick(self, now):
        if self.approve_at > self.approve_done:  # MQTT로 허락이 새로 왔다
            self.approve_done = self.approve_at
            self.remote_approve(now)
        if self.state == "idle":
            self.show_idle(now)
        elif self.state == "face":
            if self.faces is not None:
                self.face = self.faces.result_since(self.card_time - FACE_BEFORE_SEC)
            if self.face == "match" or now >= self.deadline:
                self.after_face(now)
        elif self.state == "password":
            if now >= self.deadline:
                self.fail(now, "TIME OUT")
        elif self.state == "approve":
            if now >= self.deadline:
                self.fail(now, "NO APPROVAL")
        elif now >= self.deadline:  # open, message
            if self.state == "open":
                self.uno.door(False)
                self.message(now, "DOOR LOCKED", "", seconds=1)
            else:
                self.state = "idle"

    def remote_approve(self, now):
        """월패드나 폰의 출입 허락. 인증 중 허락을 기다리고 있었으면 인증 성공, 아니면 원격으로 문을 연다."""
        ok = self.approve_ok == 1
        log.info("Approval from wallpad/phone: ok=%s", self.approve_ok)
        if self.state == "approve":
            if ok:
                self.success(now)
            else:
                self.fail(now, "NOT APPROVED")
        elif ok and self.state != "open":
            self.open_door(now, "approve", "REMOTE OPEN")

    def risk_score(self, now):
        parts = []
        if time.localtime().tm_hour < 6:
            parts.append(("night", SCORE_NIGHT))
        if self.face != "match":
            parts.append((f"face {self.face}", SCORE_FACE))
        # 허브가 보내는 loiter_until(서성임 시각 + 10분)도 보되, 출입 성공 전에 생긴 것은 뺀다
        hub_loiter = (self.loiter_until > time.time()
                      and self.loiter_until - LOITER_MEMORY_SEC > self.loiter_cleared)
        if self.loiter.recent(now, LOITER_MEMORY_SEC) or hub_loiter:
            parts.append(("loiter", SCORE_LOITER))
        if self.mode == "away":
            parts.append(("away", SCORE_AWAY))
        if self.pw_errors:
            parts.append((f"{self.pw_errors} wrong pw", self.pw_errors * SCORE_PW_ERROR))
        score = sum(points for _, points in parts)
        log.info("Risk score %d (%s)", score, ", ".join(f"{name} +{points}" for name, points in parts) or "nothing")
        return score

    def after_face(self, now):
        self.score = self.risk_score(now)
        # 네트워크가 끊겨 혼자 판단할 때는 점수와 상관없이 비밀번호를 묻는다 (제안서 7.5)
        if self.score >= NEED_PASSWORD or not self.node.connected:
            self.method = "card+pw"
            self.ask_password(now, self.with_risk("PASSWORD"))
        else:
            self.check_approval(now)

    def ask_password(self, now, top):
        self.state, self.deadline, self.typed = "password", now + PASSWORD_TIMEOUT_SEC, ""
        self.show(top, "PW:")

    def submit_password(self, now):
        if check_password(self.typed, self.data):
            self.sound(OK_BEEP)
            self.check_approval(now)
            return
        self.pw_errors += 1
        self.publish("home/door/pwfail", {"count": self.pw_errors})
        self.score = self.risk_score(now)  # 틀릴 때마다 +1
        if self.pw_errors >= MAX_PW_ERRORS:
            self.locked_until = now + LOCKOUT_SEC
            self.fail(now, "WRONG 3 TIMES", ALARM)
        else:
            self.sound(ERROR_BEEP)
            self.ask_password(now, self.with_risk(f"WRONG {self.pw_errors}/{MAX_PW_ERRORS}"))

    def check_approval(self, now):
        """마지막 단계. 점수가 높거나 경보 중이면 월패드(또는 폰) 허락을 기다린다."""
        self.score = self.risk_score(now)  # 비밀번호 오류가 더해졌을 수 있다
        need = self.score >= NEED_APPROVE or self.suspicion >= ALARM_LEVEL
        if need and self.node.connected:
            self.method += "+approve"
            self.state, self.deadline = "approve", now + APPROVE_TIMEOUT_SEC
            self.show(self.with_risk("APPROVAL"), "CHECK WALLPAD")
        else:
            self.success(now)

    def success(self, now):
        self.publish("home/door/auth", {"result": "ok", "method": self.method, "face": self.face,
                                        "score": self.score})
        self.pw_errors = 0
        self.loiter.forget()  # 앞서 있던 서성임은 본인이었다고 보고 다음 출입 점수에서 뺀다
        self.loiter_cleared = time.time()
        self.open_door(now, "auth", f"WELCOME {self.name.upper()}", self.with_risk("DOOR OPEN"))

    def fail(self, now, reason, notes=ERROR_BEEP):
        log.info("Not opened: %s", reason)
        self.publish("home/door/auth", {"result": "fail", "method": self.method, "face": self.face,
                                        "score": self.score})
        self.message(now, reason, "", notes)

    def open_door(self, now, by, greeting, top="DOOR OPEN"):
        """문 열기. by: "auth"(인증) / "approve"(원격 허락) / "exit"(나가기 버튼). OPEN_SEC 뒤 tick이 잠근다."""
        self.state, self.deadline = "open", now + OPEN_SEC
        self.uno.door(True)
        self.show(top, greeting)
        self.sound(OPEN_MELODY)
        if by != "exit":  # 나가기 버튼은 home/door/exit 로 이미 알렸다
            self.publish("home/door/open", {"state": "open", "by": by})


def main():
    parser = argparse.ArgumentParser(description="Front door: card, remote password, face -> MQTT")
    parser.add_argument("--port", help="Uno serial port (e.g. COM5). Found automatically if omitted")
    parser.add_argument("--fake", action="store_true", help="no Uno: type inputs on the keyboard")
    parser.add_argument("--no-camera", action="store_true", help="no camera: the face counts as not seen")
    parser.add_argument("--camera", type=int, default=0, help="camera number (default 0)")
    parser.add_argument("--broker", help="use only this broker, e.g. localhost or localhost:1884")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    data = load_data()
    if not data["cards"]:
        log.warning("No cards yet. Run: python door_setup.py card NAME")
    if not data["password"]:
        log.warning("No password yet. Run: python door_setup.py password")

    config = None
    if args.broker:
        host, _, port = args.broker.partition(":")
        config = {**load_config(), "brokers": [{"host": host, "port": int(port or 1883)}]}
    node = Node("door", config)

    faces = None
    if not args.no_camera:
        from face_watch import FaceWatch
        faces = FaceWatch(args.camera)
    if args.fake:
        from fake_uno import FakeUno
        uno = FakeUno()
    else:
        from uno_link import Uno
        uno = Uno(args.port)

    door = Door(uno, node, faces, data, LoiterWatch())
    node.start()
    log.info("Door ready. Uno: %s, camera: %s, broker: %s. Quit: Ctrl+C",
             uno.port, "off" if faces is None else "on", node.broker["host"])
    try:
        while True:
            line = uno.read_line()  # 최대 0.05초 기다린다
            if line:
                door.handle(line, monotonic())
            door.tick(monotonic())
    except KeyboardInterrupt:
        pass
    finally:
        uno.door(False)  # 열린 채로 끝나지 않게
        door.show("DOOR PROGRAM", "STOPPED")
        uno.close()
        if faces is not None:
            faces.close()
        node.stop()


if __name__ == "__main__":
    main()
