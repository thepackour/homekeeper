"""얼굴 인식. 카메라 앞 사람이 등록된 사람인지 표시한다.

얼굴 찾기는 매 화면, 누구인지 비교는 0.5초에 한 번만 해서 Pi에서도 가볍게 돌린다.
창에서 q를 누르거나 터미널에서 Ctrl+C를 누르면 끝난다.
"""
import argparse
from time import monotonic

import cv2

from face_common import FaceEngine, draw_face, identify, load_database, open_camera

RECOGNIZE_INTERVAL = 0.5
WINDOW = "Recognize (q: quit)"

parser = argparse.ArgumentParser(description="Recognize enrolled faces")
parser.add_argument("--headless", action="store_true", help="no preview window (for Pi over ssh)")
args = parser.parse_args()

database = load_database()
if not database:
    raise SystemExit("No faces saved yet. Run: python enroll.py NAME")

engine = FaceEngine()
camera = open_camera()
last_check = 0.0
label = "no face"
shown = None

print(f"Enrolled: {', '.join(database)}. Quit: q in the window or Ctrl+C")
try:
    while True:
        ok, frame = camera.read()
        if not ok:
            print("Could not read from the camera")
            break

        face = engine.largest_face(frame)
        if face is None:
            label = "no face"
            current = label
        elif monotonic() - last_check >= RECOGNIZE_INTERVAL:
            last_check = monotonic()
            name, score = identify(engine.feature(frame, face), database)
            current = name or "unknown"
            label = f"{current} {score:.2f}"
        else:
            current = shown

        if current != shown:
            print(label)
            shown = current

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
