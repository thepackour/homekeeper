"""얼굴 등록. 사용법: python enroll.py 이름

카메라를 보고 있으면 얼굴 특징값 5개를 모아 face_db/이름.npy로 저장한다. 사진은 저장하지 않는다.
창에서 q를 누르면 저장하지 않고 끝난다. 같은 이름으로 다시 등록하면 새 값으로 바뀐다.
"""
import argparse
import re
from time import monotonic

import cv2
import numpy as np

from face_common import FACE_DB, FaceEngine, draw_face, open_camera

SAMPLE_COUNT = 5
SAMPLE_INTERVAL = 0.7
MIN_FACE_WIDTH = 80
WINDOW = "Enroll (q: quit)"

parser = argparse.ArgumentParser(description="Save a person's face features")
parser.add_argument("name", help="English letters, numbers, _ or -")
parser.add_argument("--headless", action="store_true", help="no preview window (for Pi over ssh)")
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
    parser.error("Use only English letters, numbers, _ or - in the name")

engine = FaceEngine()
camera = open_camera()
samples = []
last_sample = 0.0

print(f"Enrolling {args.name}. Look at the camera and turn your head a little")
try:
    while len(samples) < SAMPLE_COUNT:
        ok, frame = camera.read()
        if not ok:
            print("Could not read from the camera")
            break

        face = engine.largest_face(frame)
        label = f"{len(samples)}/{SAMPLE_COUNT}"
        if face is None:
            label += " no face"
        elif face[2] < MIN_FACE_WIDTH:
            label += " move closer"
        elif monotonic() - last_sample >= SAMPLE_INTERVAL:
            samples.append(engine.feature(frame, face))
            last_sample = monotonic()
            print(f"Sample {len(samples)}/{SAMPLE_COUNT}")

        if not args.headless:
            draw_face(frame, face, label)
            cv2.imshow(WINDOW, frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
except KeyboardInterrupt:
    print()
finally:
    camera.release()
    if not args.headless:
        cv2.destroyAllWindows()

if len(samples) == SAMPLE_COUNT:
    FACE_DB.mkdir(exist_ok=True)
    np.save(FACE_DB / f"{args.name}.npy", np.array(samples))
    print(f"Saved {args.name}")
else:
    print("Not saved")
