"""검출 확인 + 속도 측정. 레포 맨 위에서:

    python -m living.detect_view                         # config.json 의 카메라
    python -m living.detect_view --source videos/a.mp4   # 녹화 영상
    python -m living.detect_view --type effdet           # 모델 바꾸기
    python -m living.detect_view --no-show               # 화면 없이 속도만(파이 SSH 등)

q 로 종료. 끝나면 평균 검출 시간을 출력한다.
"""
import argparse
import json
import time

import cv2

from living.camera import Camera
from living.detector import make_detector

p = argparse.ArgumentParser()
p.add_argument("--source")
p.add_argument("--type", choices=["yolo", "effdet"])
p.add_argument("--no-show", action="store_true")
args = p.parse_args()

cfg = json.load(open("living/config.json", encoding="utf-8"))
if args.type:
    cfg["detector"]["type"] = args.type
source = args.source or cfg["camera"]["source"]

detector = make_detector(cfg["detector"])
times = []

with Camera(source, cfg["camera"]["width"], cfg["camera"]["height"]) as cam:
    cam.set_exposure(cfg["camera"].get("exposure"))
    while True:
        frame = cam.read()
        if frame is None:
            break
        t0 = time.perf_counter()
        people = detector.detect(frame)
        times.append(time.perf_counter() - t0)

        if args.no_show:
            continue
        for x1, y1, x2, y2, s in people:
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 200, 0), 2)
            cv2.putText(frame, f"{s:.2f}", (int(x1), int(y1) - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)
        cv2.putText(frame, f"{len(people)} people  {1000 * times[-1]:.0f} ms", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imshow("detect", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

cv2.destroyAllWindows()
detector.close()
if times:
    avg = sum(times[1:] or times) / len(times[1:] or times)   # 첫 프레임(준비 시간) 제외
    print(f"{cfg['detector']['type']}: 프레임 {len(times)}개, 평균 {avg * 1000:.1f} ms ({1 / avg:.1f} fps)")
