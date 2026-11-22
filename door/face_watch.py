"""현관 카메라를 계속 보면서 얼굴 결과를 기억한다. 현관 프로그램이 카드를 받으면 결과를 물어본다.

얼굴 찾기와 비교는 0.5초에 한 번만 해서 Pi 400에서도 가볍게 돌린다.
방문자 사진(작은 JPEG)도 여기서 만든다.
"""
import base64
import threading
from time import monotonic, sleep

import cv2

from face_common import FaceEngine, identify, load_database, open_camera

CHECK_INTERVAL_SEC = 0.5
PHOTO_SIZE = (320, 240)
PHOTO_QUALITY = 70


class FaceWatch:
    def __init__(self, camera_index=0):
        self.database = load_database()
        if not self.database:
            print("No faces enrolled yet. Every face will count as unknown (python enroll.py NAME)")
        self.engine = FaceEngine()
        self.camera = open_camera(camera_index)
        self.lock = threading.Lock()
        self.frame = None
        self.last_face = 0.0   # 얼굴을 본 마지막 시각 (누구든)
        self.last_match = 0.0  # 등록된 얼굴을 본 마지막 시각
        self.last_name = None
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        last_check = 0.0
        while not self.stopped.is_set():
            ok, frame = self.camera.read()  # 오래된 화면이 쌓이지 않게 계속 읽는다
            if not ok:
                sleep(0.5)
                continue
            with self.lock:
                self.frame = frame
            now = monotonic()
            if now - last_check < CHECK_INTERVAL_SEC:
                continue
            last_check = now
            face = self.engine.largest_face(frame)
            if face is None:
                continue
            self.last_face = now
            name, _ = identify(self.engine.feature(frame, face), self.database)
            if name:
                self.last_match = now
                self.last_name = name

    def result_since(self, since):
        """since 이후에 본 얼굴: "match"(등록된 사람) / "mismatch"(모르는 사람) / "none"(얼굴 없음)."""
        if self.last_match >= since:
            return "match"
        if self.last_face >= since:
            return "mismatch"
        return "none"

    def photo_base64(self):
        """지금 화면을 320x240 JPEG로 줄여 base64 글자로 돌려준다. 수십 KB라 MQTT로 보내도 된다."""
        with self.lock:
            frame = self.frame
        if frame is None:
            return None
        small = cv2.resize(frame, PHOTO_SIZE)
        ok, data = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, PHOTO_QUALITY])
        return base64.b64encode(data.tobytes()).decode("ascii") if ok else None

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)
        self.camera.release()
