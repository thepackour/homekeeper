"""얼굴 인식 공통 코드. YuNet으로 얼굴을 찾고 SFace로 특징값을 만든다.

Pi 3B에서도 돌릴 수 있게 작은 int8 모델을 쓰고, 얼굴 찾기는 절반 크기 화면에서 한다.
Pi 터미널에 한글이 안 보여서 출력은 영어로 한다.
"""
import os
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"
DETECTOR_MODEL = "face_detection_yunet_2023mar_int8.onnx"
RECOGNIZER_MODEL = "face_recognition_sface_2021dec_int8.onnx"
FACE_DB = BASE_DIR / "face_db"

FRAME_WIDTH = 640
FRAME_HEIGHT = 480
DETECT_SCALE = 0.5
SCORE_THRESHOLD = 0.8
MATCH_THRESHOLD = 0.363  # OpenCV SFace 예제의 코사인 유사도 기준값


class FaceEngine:
    def __init__(self):
        for name in (DETECTOR_MODEL, RECOGNIZER_MODEL):
            if not (MODEL_DIR / name).exists():
                raise SystemExit(f"Model file missing: models/{name}")

        # Windows의 OpenCV는 한글 경로를 못 열어서 폴더로 들어가 파일 이름만 넘긴다.
        previous = Path.cwd()
        os.chdir(MODEL_DIR)
        try:
            size = (int(FRAME_WIDTH * DETECT_SCALE), int(FRAME_HEIGHT * DETECT_SCALE))
            self.detector = cv2.FaceDetectorYN.create(DETECTOR_MODEL, "", size, SCORE_THRESHOLD)
            self.recognizer = cv2.FaceRecognizerSF.create(RECOGNIZER_MODEL, "")
        finally:
            os.chdir(previous)

    def largest_face(self, frame):
        """화면에서 가장 큰 얼굴을 돌려준다. 없으면 None."""
        small = cv2.resize(frame, None, fx=DETECT_SCALE, fy=DETECT_SCALE)
        height, width = small.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(small)
        if faces is None:
            return None
        face = max(faces, key=lambda item: item[2] * item[3]).copy()
        face[:14] /= DETECT_SCALE  # 위치 값을 원래 화면 크기로 되돌린다
        return face

    def feature(self, frame, face):
        """얼굴 하나의 특징값(숫자 128개)을 만든다."""
        aligned = self.recognizer.alignCrop(frame, face)
        return self.recognizer.feature(aligned).flatten().copy()


def open_camera(index=0):
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    camera = cv2.VideoCapture(index, backend)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    if not camera.isOpened():
        raise SystemExit("Camera not found. Check the webcam or close other camera apps")
    return camera


def load_database():
    """저장된 사람별 특징값을 읽는다."""
    return {path.stem: np.load(path) for path in sorted(FACE_DB.glob("*.npy"))}


def identify(feature, database):
    """가장 닮은 사람과 점수를 돌려준다. 기준보다 낮으면 이름은 None."""
    best_name, best_score = None, -1.0
    unit = feature / np.linalg.norm(feature)
    for name, samples in database.items():
        units = samples / np.linalg.norm(samples, axis=1, keepdims=True)
        score = float((units @ unit).max())
        if score > best_score:
            best_name, best_score = name, score
    if best_score < MATCH_THRESHOLD:
        return None, best_score
    return best_name, best_score


def draw_face(frame, face, label):
    if face is not None:
        x, y, width, height = face[:4].astype(int)
        cv2.rectangle(frame, (x, y), (x + width, y + height), (0, 200, 0), 2)
    cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0), 2)
