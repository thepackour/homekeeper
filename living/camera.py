"""웹캠 또는 녹화 영상에서 프레임을 받는다."""
import logging
import platform
import subprocess
import time

import cv2

log = logging.getLogger("homekeeper.living.camera")
IS_LINUX = platform.system() == "Linux"


class Camera:
    """source: 웹캠 번호(0, 1, ...) 또는 영상 파일 경로.

    영상 파일일 때만 쓰는 옵션(파이에서 실제로 처리되는 속도를 흉내 낸다):
      fps:      초당 이 장수만 처리하고 나머지는 건너뜀. 결과가 매번 같아서 모델 비교에 좋다.
      realtime: 처리하는 동안 실제로 흐른 시간만큼 프레임을 건너뜀. 파이에서 돌리면 실제 시연과 같다.
    read() 후 self.t 에 그 프레임의 시각(초)이 들어 있다.
    """

    def __init__(self, source=0, width=640, height=480, fps=None, realtime=False):
        self.source = source
        self.is_file = isinstance(source, str)
        self.target_fps, self.realtime = fps, realtime
        self.t = 0.0
        self._idx = -1
        self._start = None
        if self.is_file:
            self.cap = cv2.VideoCapture(source)
            self.file_fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        else:
            backend = cv2.CAP_V4L2 if IS_LINUX else cv2.CAP_DSHOW
            self.cap = cv2.VideoCapture(source, backend)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self.cap.isOpened():
            raise RuntimeError(f"카메라를 열 수 없음: {source}")

    def read(self):
        """프레임 하나. 영상이 끝났거나 실패하면 None."""
        if not self.is_file:
            ok, frame = self.cap.read()
            self.t = time.monotonic()
            return frame if ok else None

        if self.realtime:
            now = time.perf_counter()
            if self._start is None:
                self._start = now
            want = max(self._idx + 1, int((now - self._start) * self.file_fps))
        elif self.target_fps:
            want = self._idx + max(1, round(self.file_fps / self.target_fps))
        else:
            want = self._idx + 1
        while self._idx < want - 1:          # 건너뛸 프레임은 해독 없이 넘김
            if not self.cap.grab():
                return None
            self._idx += 1
        ok, frame = self.cap.read()
        if not ok:
            return None
        self._idx += 1
        self.t = self._idx / self.file_fps
        return frame

    def set_exposure(self, value):
        """노출을 수동으로 고정한다. 스트림을 연 직후에 부를 것(C922는 열 때 초기화됨).

        리눅스(파이): v4l2-ctl 사용. value는 exposure_time_absolute 값(C922 대략 3~2047).
        그 외: 아무것도 하지 않는다(노트북 개발 중에는 자동 노출 그대로).
        """
        if self.is_file or value is None:
            return
        if not IS_LINUX:
            log.info("리눅스가 아니라 노출 설정은 건너뜀")
            return
        dev = f"/dev/video{self.source}"
        # 커널 버전에 따라 이름이 다름: 새 이름 먼저, 안 되면 옛 이름
        for ctrls in (f"auto_exposure=1,exposure_time_absolute={value}",
                      f"exposure_auto=1,exposure_absolute={value}"):
            r = subprocess.run(["v4l2-ctl", "-d", dev, "-c", ctrls], capture_output=True, text=True)
            if r.returncode == 0:
                log.info("노출 고정: %s", value)
                return
        log.warning("노출 설정 실패: %s", r.stderr.strip())

    def release(self):
        self.cap.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
