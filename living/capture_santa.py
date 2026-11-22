"""산타 학습용 사진 찍기. 레포 맨 위에서:

    python -m living.capture_santa              # config.json 의 카메라
    python -m living.capture_santa --source 1   # 웹캠 1번

  스페이스  지금 화면 한 장 저장
  a        자동 저장 켜기/끄기 (0.5초마다 한 장)
  q        종료

저장 위치: santa_data/images/ (git에 올리지 않음)
시연할 자리, 시연할 조명에서 찍는다. 산타 위치, 거리, 방향을 계속 바꿔 가며 찍고
두 개가 같이 있는 사진, 문을 지나가는 중인 사진, 산타 없는 빈 화면(20~30장)도 넣는다.
"""
import argparse
import json
import time
from pathlib import Path

import cv2

from living.camera import Camera

p = argparse.ArgumentParser()
p.add_argument("--source")
p.add_argument("--out", default="santa_data/images")
p.add_argument("--every", type=float, default=0.5, help="자동 저장 간격(초)")
args = p.parse_args()

cfg = json.load(open("living/config.json", encoding="utf-8"))
source = args.source or cfg["camera"]["source"]
if isinstance(source, str) and source.isdigit():
    source = int(source)

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
count = len(list(out.glob("*.jpg")))
auto, last = False, 0.0

with Camera(source, cfg["camera"]["width"], cfg["camera"]["height"]) as cam:
    cam.set_exposure(cfg["camera"].get("exposure"))
    while True:
        frame = cam.read()
        if frame is None:
            break
        now = time.time()
        save = auto and now - last >= args.every
        key = cv2.waitKey(1) & 0xFF
        if key == ord(" "):
            save = True
        elif key == ord("a"):
            auto = not auto
        elif key == ord("q"):
            break
        if save:
            count += 1
            cv2.imwrite(str(out / f"santa_{int(now * 1000)}.jpg"), frame)
            last = now
        view = frame.copy()
        cv2.putText(view, f"{count} saved  auto:{'ON' if auto else 'off'}  [space]save [a]auto [q]quit",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imshow("capture", view)

cv2.destroyAllWindows()
print(f"저장된 사진: {count}장 → {out}")
