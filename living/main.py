"""거실 노드 본 프로그램. 레포 맨 위에서:

    python -m living.main                          # 실제 운영(웹캠 + 아두이노)
    python -m living.main --source videos/a.mp4    # 영상으로 테스트(실제 속도로 재생)
    python -m living.main --show                   # 처리 화면 보기
    python -m living.main --no-arduino             # 아두이노 없이

하는 일
  - home/cmd/living/camera {"on":1,"sec":10} → 카메라를 켜고 sec 초 동안 들어오고 나간 사람을 센 뒤
    home/living/count 를 한 번 보낸다. 세는 중에 또 오면 시간을 연장한다.
    {"warm":1} 이면 카메라만 미리 열어 둔다(warm_sec 초 안에 명령이 없으면 닫음).
  - home/alert 꼬리물기 → 마지막으로 센 사람들의 베스트샷을 home/living/snapshot 으로 보내고 부저.
  - 아두이노 PIR 이 바뀌면 home/living/motion.
  - 카메라가 켜진 동안 촬영 표시등, 어두우면 보조 조명.
"""
import argparse
import base64
import json
import logging
import queue
import threading
import time

import cv2

from common.mqtt_node import Node
from living.arduino import Arduino
from living.camera import Camera
from living.counter import PeopleCounter
from living.detector import make_detector

log = logging.getLogger("homekeeper.living")


class LivingNode:
    def __init__(self, cfg, source=None, show=False, use_arduino=True):
        self.cfg = cfg
        self.cam_cfg = cfg["camera"]
        self.source = self.cam_cfg["source"] if source is None else source
        self.show = show
        self.window_sec = cfg.get("window_sec", 10)
        self.max_window_sec = cfg.get("max_window_sec", 15)
        self.warm_sec = cfg.get("warm_sec", 5)

        self.detector = make_detector(cfg["detector"])   # 모델 로딩은 오래 걸려서 처음 한 번만
        self.node = Node("living")
        ser = cfg.get("arduino", {})
        self.arduino = Arduino(ser.get("port", "auto") if use_arduino else None,
                               ser.get("baud", 9600), on_pir=self._on_pir)

        self.cmds = queue.Queue()      # MQTT 스레드 → 카메라 스레드
        self.cam = None
        self.counter = None
        self.count_start = self.count_until = 0.0
        self.warm_until = 0.0
        self.last_counter = None       # 마지막으로 센 결과(snapshot 용)
        self._stop = threading.Event()

        self.node.on("home/cmd/living/camera")(self._on_camera_cmd)
        self.node.on("home/alert")(self._on_alert)

    # ---------- MQTT·아두이노 콜백 (빨리 끝내야 함: 무거운 일은 카메라 스레드로) ----------

    def _on_camera_cmd(self, msg, topic):
        log.info("카메라 명령 %s", msg)
        self.cmds.put(("camera", msg))

    def _on_alert(self, msg, topic):
        if msg.get("type") == "tailgate":
            self.cmds.put(("snapshot", msg))
            self.arduino.beep(3)

    def _on_pir(self, state):
        log.info("PIR %s", state)
        self.node.publish("home/living/motion", {"state": state})

    # ---------- 실행 ----------

    def run(self):
        self.arduino.start()
        self.node.start()
        log.info("거실 노드 시작 (카메라 %s, 검출 %s)", self.source, self.cfg["detector"]["type"])
        try:
            self._loop()
        except KeyboardInterrupt:
            pass
        finally:
            self._close_camera()
            self.arduino.stop()
            self.node.stop()
            self.detector.close()
            if self.show:
                cv2.destroyAllWindows()

    def _loop(self):
        while not self._stop.is_set():
            busy = self.counter is not None
            try:
                kind, msg = self.cmds.get(timeout=0 if busy else (0.05 if self.cam else 0.5))
                self._handle(kind, msg)
            except queue.Empty:
                pass
            now = time.monotonic()
            if self.counter is not None:
                self._count_step(now)
            elif self.cam is not None:
                if now >= self.warm_until:
                    log.info("예열 시간 끝, 카메라 끔")
                    self._close_camera()
                else:
                    self.cam.cap.grab()        # 버퍼에 옛 프레임이 쌓이지 않게 비움

    def _handle(self, kind, msg):
        now = time.monotonic()
        if kind == "snapshot":
            self._send_snapshot()
            return
        if not msg.get("on", 1):
            if self.counter is not None:
                self._finish()
            self._close_camera()
            return
        if not self._open_camera():
            return
        if msg.get("warm"):
            self.warm_until = max(self.warm_until, now + self.warm_sec)
            log.info("카메라 예열 (%s초)", self.warm_sec)
            return
        sec = msg.get("sec", self.window_sec)
        if self.counter is None:
            frame = self.cam.read()
            width = frame.shape[1] if frame is not None else self.cam_cfg["width"]
            self.counter = PeopleCounter(self.cfg, width, detector=self.detector)
            self.count_start = now
            self.count_until = now + sec
            self.arduino.beep(1)
            log.info("인원 세기 시작 (%s초)", sec)
        else:
            self.count_until = max(self.count_until, now + sec)
            log.info("세는 시간 연장 (%.1f초 남음)", self.count_until - now)

    def _count_step(self, now):
        frame = self.cam.read()
        if frame is None:                  # 영상 파일이 끝났거나 카메라 오류
            log.warning("프레임 없음, 지금까지 센 것으로 끝냄")
            self._finish()
            self._close_camera()
            return
        boxes, tracks, events = self.counter.process(frame, self.cam.t)
        for kind, tid in events:
            log.info("%s #%s", "들어옴" if kind == "in" else "나감", tid)
        if self.show:
            self._draw(frame, tracks)
        if now >= self.count_until:
            # 끝나는 순간 선 근처에 사람이 있으면 max_window_sec 까지 기다린다
            line = self.counter.line
            near = any(abs(tr.center[0] - line.line_x) < line.emerge_zone for tr in tracks) or line.pending
            if near and now - self.count_start < self.max_window_sec:
                return
            self._finish()
            if time.monotonic() >= self.warm_until:
                self._close_camera()

    def _finish(self):
        result = self.counter.result()
        self.node.publish("home/living/count", result)
        log.info("결과 발행: 들어옴 %s, 나감 %s", result["count"], result["out"])
        self.last_counter = self.counter
        self.counter = None

    def _send_snapshot(self):
        if self.last_counter is None:
            log.info("보낼 사진 없음")
            return
        q = self.cfg.get("snapshot_quality", 70)
        imgs = []
        for tid, img in self.last_counter.best_shots().items():
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
            if ok:
                imgs.append({"id": tid, "img": base64.b64encode(buf).decode()})
        self.node.publish("home/living/snapshot", {"imgs": imgs})
        log.info("사진 %s장 전송", len(imgs))

    # ---------- 카메라 ----------

    def _open_camera(self):
        if self.cam is not None:
            return True
        try:
            if isinstance(self.source, str):
                self.cam = Camera(self.source, realtime=True)
            else:
                self.cam = Camera(self.source, self.cam_cfg["width"], self.cam_cfg["height"])
        except RuntimeError as e:
            log.error("%s", e)
            self.cam = None
            return False
        lux = self.arduino.lux
        self.cam.set_exposure(self._exposure_for(lux))
        self.arduino.led(1)
        dark = self.cfg.get("dark_lux")
        if lux is not None and dark is not None and lux < dark:
            self.arduino.lamp(1)
        log.info("카메라 켬 (조도 %s)", lux)
        return True

    def _exposure_for(self, lux):
        """config 의 exposure_table [[조도 이상, 노출], ...] 에서 고른다. 없으면 camera.exposure."""
        table = self.cam_cfg.get("exposure_table") or []
        if lux is not None and table:
            for min_lux, value in sorted(table, reverse=True):
                if lux >= min_lux:
                    return value
            return sorted(table)[0][1]
        return self.cam_cfg.get("exposure")

    def _close_camera(self):
        if self.cam is None:
            return
        self.cam.release()
        self.cam = None
        self.warm_until = 0.0
        self.arduino.led(0)
        self.arduino.lamp(0)
        log.info("카메라 끔")

    def _draw(self, frame, tracks):
        line = self.counter.line
        x = int(line.line_x)
        cv2.line(frame, (x, 0), (x, frame.shape[0]), (0, 255, 255), 2)
        for tr in tracks:
            x1, y1, x2, y2 = map(int, tr.box[:4])
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
            cv2.putText(frame, f"#{tr.id}", (x1, max(15, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)
        cv2.putText(frame, f"IN {line.count_in}  OUT {line.count_out}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imshow("living", frame)
        cv2.waitKey(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="웹캠 번호 또는 영상 파일(테스트용)")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-arduino", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    cfg = json.load(open("living/config.json", encoding="utf-8"))
    source = args.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)
    LivingNode(cfg, source, args.show, not args.no_arduino).run()


if __name__ == "__main__":
    main()
