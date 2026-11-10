"""녹화 영상으로 모델별 인원 계수 정확도와 속도를 채점한다. 레포 맨 위에서:

    python -m living.evaluate videos                     # 두 모델, 초당 5장 처리로 흉내
    python -m living.evaluate videos --fps 3             # 파이에서 잰 속도에 맞춰
    python -m living.evaluate videos --realtime          # 파이에서 직접 돌릴 때(실제 속도 그대로)
    python -m living.evaluate videos --models yolo --show   # 한 모델, 화면으로 확인
    python -m living.evaluate videos --show --delay 300     # 천천히(프레임마다 0.3초)
    python -m living.evaluate videos --save captures        # 결과 영상 저장(발표용)

--show 중: 스페이스 일시정지, s 지금 화면 캡처(PNG), q 다음 영상

정답은 파일 이름에서 읽는다: S3_close_in2_01.mp4 → 들어옴 2, 나감 0
결과는 results.csv(영상별)로 저장하고 요약을 출력한다.
"""
import argparse
import csv
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import cv2

from living.camera import Camera
from living.counter import PeopleCounter
from living.detector import make_detector

TAILGATE = {"S3", "S4", "S6"}         # 꼬리물기 검출률
NORMAL = {"S1", "S5", "S7", "S8"}     # 오경보율


def truth_of(name):
    sc = re.match(r"(S\d+)", name)
    tin = re.search(r"_in(\d+)", name)
    tout = re.search(r"_out(\d+)", name)
    return (sc.group(1) if sc else "?", int(tin.group(1)) if tin else 0, int(tout.group(1)) if tout else 0)


def annotate(frame, counter, tracks, recent, title):
    """선, 사람 상자와 ID, 현재 계수, 최근 이벤트를 그린 이미지를 돌려준다."""
    img = frame.copy()
    h, w = img.shape[:2]
    line = counter.line
    x = int(line.line_x)
    # 선과 띠, 어느 쪽이 거실인지
    band = img.copy()
    cv2.rectangle(band, (int(x - line.margin), 0), (int(x + line.margin), h), (0, 255, 255), -1)
    img = cv2.addWeighted(band, 0.15, img, 0.85, 0)
    cv2.line(img, (x, 0), (x, h), (0, 255, 255), 2)
    left, right = ("OUT", "IN") if line.in_dir == "right" else ("IN", "OUT")
    cv2.putText(img, left, (x - 60, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.putText(img, right, (x + 15, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    # 사람: 초록 = 추적 중, 주황 = 가려졌다 나타나 확인 중
    for tr in tracks:
        x1, y1, x2, y2 = map(int, tr.box[:4])
        color = (0, 165, 255) if tr.id in line.pending else (0, 200, 0)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, f"#{tr.id}", (x1 + 3, max(78, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cx, cy = map(int, tr.center)
        vx, vy = tr.velocity
        cv2.arrowedLine(img, (cx, cy), (int(cx + vx * 0.3), int(cy + vy * 0.3)), color, 2, tipLength=0.3)
    # 위쪽 정보 띠
    cv2.rectangle(img, (0, 0), (w, 58), (0, 0, 0), -1)
    cv2.putText(img, title, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    r = counter.result()
    cv2.putText(img, f"IN {r['count']}   OUT {r['out']}", (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
    # 방금 센 사람(1초 동안 표시)
    for i, (kind, tid) in enumerate(recent):
        cv2.putText(img, f"+1 {kind.upper()} #{tid}", (w - 170, 48 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                    (0, 255, 0) if kind == "in" else (255, 128, 0), 2)
    return img


def run_clip(path, cfg, detector, fps, realtime, show, delay=0, save_dir=None, model=""):
    sc, tin, tout = truth_of(path.stem)
    writer = None
    shots = 0
    with Camera(str(path), fps=fps, realtime=realtime) as cam:
        counter = None
        times, recent = [], []
        while True:
            frame = cam.read()
            if frame is None:
                break
            if counter is None:
                counter = PeopleCounter(cfg, frame.shape[1], detector=detector)
            t0 = time.perf_counter()
            boxes, tracks, events = counter.process(frame, cam.t)
            times.append(time.perf_counter() - t0)
            if not (show or save_dir):
                continue

            recent = [(k, i, t) for k, i, t in recent if cam.t - t < 1.0] + [(k, i, cam.t) for k, i in events]
            title = f"{model}  {path.name}  t={cam.t:.1f}s  truth in {tin} / out {tout}"
            img = annotate(frame, counter, tracks, [(k, i) for k, i, _ in recent], title)
            if save_dir:
                if writer is None:
                    out = Path(save_dir) / f"{path.stem}_{model}.mp4"
                    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"),
                                             fps or cam.file_fps, (img.shape[1], img.shape[0]))
                writer.write(img)
            if show:
                cv2.imshow("evaluate", img)
                key = cv2.waitKey(max(1, delay)) & 0xFF
                if key == ord(" "):                   # 스페이스: 일시정지, 다시 누르면 계속
                    key = cv2.waitKey(0) & 0xFF
                    while key not in (ord(" "), ord("q"), ord("s")):
                        key = cv2.waitKey(0) & 0xFF
                if key == ord("s"):                   # s: 지금 화면 캡처
                    Path(save_dir or "captures").mkdir(exist_ok=True)
                    shots += 1
                    png = Path(save_dir or "captures") / f"{path.stem}_{model}_{cam.t:.1f}s.png"
                    cv2.imwrite(str(png), img)
                    print(f"  캡처: {png}")
                if key == ord("q"):
                    break
    if writer:
        writer.release()
    r = counter.result() if counter else {"count": 0, "out": 0}
    return r["count"], r["out"], times


def main():
    p = argparse.ArgumentParser()
    p.add_argument("videos")
    p.add_argument("--models", nargs="+", default=["yolo", "effdet"])
    p.add_argument("--fps", type=float, default=5, help="초당 처리 장수(파이 속도 흉내)")
    p.add_argument("--realtime", action="store_true", help="실제 처리 시간만큼 건너뜀(파이에서)")
    p.add_argument("--show", action="store_true", help="화면으로 보기(스페이스: 일시정지, s: 캡처, q: 다음 영상)")
    p.add_argument("--save", metavar="DIR", help="선·상자·계수를 그린 결과 영상을 DIR 에 저장")
    p.add_argument("--delay", type=int, default=0, help="--show 때 프레임마다 기다릴 ms(천천히 보기)")
    p.add_argument("--out", default="results.csv")
    args = p.parse_args()

    cfg = json.load(open("living/config.json", encoding="utf-8"))
    clips = sorted(Path(args.videos).glob("*.mp4"))
    if not clips:
        raise SystemExit(f"영상이 없음: {args.videos}")

    if args.save:
        Path(args.save).mkdir(exist_ok=True)
    rows = []
    for model in args.models:
        cfg["detector"]["type"] = model
        detector = make_detector(cfg["detector"])
        for clip in clips:
            sc, tin, tout = truth_of(clip.stem)
            cin, cout, times = run_clip(clip, cfg, detector, None if args.realtime else args.fps,
                                        args.realtime, args.show, args.delay, args.save, model)
            ms = 1000 * sum(times[1:] or times) / max(1, len(times[1:] or times))
            ok = (cin, cout) == (tin, tout)
            rows.append({"model": model, "file": clip.name, "scenario": sc, "truth_in": tin, "truth_out": tout,
                         "in": cin, "out": cout, "correct": int(ok), "ms": round(ms, 1), "frames": len(times)})
            print(f"{model:7s} {clip.name:28s} 정답 {tin}/{tout}  결과 {cin}/{cout}  {'O' if ok else 'X'}  {ms:.0f} ms")
        if hasattr(detector, "close"):
            detector.close()
    if args.show:
        cv2.destroyAllWindows()

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:   # 엑셀에서 한글 안 깨지게
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    print("\n=== 요약 ===")
    for model in args.models:
        mine = [r for r in rows if r["model"] == model]
        tg = [r for r in mine if r["scenario"] in TAILGATE]
        nm = [r for r in mine if r["scenario"] in NORMAL]
        ms = sum(r["ms"] for r in mine) / len(mine)
        line = f"{model:7s} 전체 {sum(r['correct'] for r in mine)}/{len(mine)}"
        if tg:
            line += f" | 꼬리물기 검출률 {sum(r['correct'] for r in tg) / len(tg):.0%} ({len(tg)}개)"
        if nm:
            line += f" | 오경보율 {1 - sum(r['correct'] for r in nm) / len(nm):.0%} ({len(nm)}개)"
        print(line + f" | 평균 {ms:.0f} ms")
        by = defaultdict(list)
        for r in mine:
            by[r["scenario"]].append(r["correct"])
        print("        " + "  ".join(f"{s} {sum(v)}/{len(v)}" for s, v in sorted(by.items())))
    print(f"\n영상별 결과: {args.out}")


if __name__ == "__main__":
    main()
