"""config 값 조합을 바꿔가며 인원 계수 정확도를 잰다(모델별 최적값 찾기). 레포 맨 위에서:

    python -m living.sweep videos                    # 두 모델, 초당 5장
    python -m living.sweep videos --fps 5 3          # 파이에서 잰 속도들로
    python -m living.sweep videos --models yolo

검출은 영상마다 한 번만 하고(.cache/ 에 저장) 추적·계수 값 조합만 빠르게 돌린다.
conf 는 낮게 한 번 검출해 두고 점수로 걸러서 흉내 낸다.
결과: 모델·fps별 상위 조합, '하나 빼고 검증' 정확도, sweep.csv
"""
import argparse
import csv
import itertools
import json
import pickle
from pathlib import Path

import cv2

from living.counter import LineCounter
from living.detector import make_detector
from living.evaluate import truth_of
from living.tracker import CentroidTracker

GRID = {
    "conf": [0.25, 0.3, 0.4, 0.5],
    "max_dist": [0.15, 0.2, 0.25, 0.35],
    "max_age": [0.5, 1.0, 1.5],
    "margin": [0.02, 0.03, 0.05],
    "emerge_zone": [0.0, 0.2, 0.3, 0.4],   # 0 = 가림 보정 끔
    "near": [0.1, 0.15, 0.2],
}
LOW_CONF = 0.2


def detect_all(clip, cfg, model, cache_dir):
    """영상의 모든 프레임 검출 결과 [(사람 상자들)], 영상 fps, 너비. 캐시가 있으면 읽는다."""
    d = cfg["detector"]
    key = f"{clip.stem}_{model}_{d.get('imgsz', 320)}_{clip.stat().st_size}.pkl"
    path = cache_dir / key
    if path.exists():
        return pickle.loads(path.read_bytes())
    det = make_detector({**d, "type": model, "conf": LOW_CONF})
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frames, width = [], None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        width = f.shape[1]
        frames.append(det.detect(f))
    cap.release()
    if hasattr(det, "close"):
        det.close()
    data = (frames, fps, width)
    path.write_bytes(pickle.dumps(data))
    return data


def count(frames, fps, width, run_fps, p, line_cfg):
    """camera.py 의 --fps 재생과 같은 프레임을 골라 추적·계수만 돌린다."""
    step = max(1, round(fps / run_fps))
    tracker = CentroidTracker(max_dist=p["max_dist"] * width, max_age=p["max_age"])
    line = LineCounter(width, x=line_cfg.get("x", 0.5), in_dir=line_cfg.get("in_dir", "right"),
                       margin=p["margin"], emerge_zone=p["emerge_zone"], near=p["near"])
    for idx in range(step - 1, len(frames), step):
        boxes = [b for b in frames[idx] if b[4] >= p["conf"]]
        line.update(tracker.update(boxes, idx / fps))
    return line.count_in, line.count_out


def combos():
    keys = list(GRID)
    for values in itertools.product(*GRID.values()):
        p = dict(zip(keys, values))
        if p["emerge_zone"] == 0 and p["near"] != GRID["near"][0]:
            continue                    # 보정을 끄면 near 는 의미 없음
        yield p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos")
    ap.add_argument("--models", nargs="+", default=["yolo", "effdet"])
    ap.add_argument("--fps", nargs="+", type=float, default=[5])
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", default="sweep.csv")
    args = ap.parse_args()

    cfg = json.load(open("living/config.json", encoding="utf-8"))
    clips = sorted(Path(args.videos).glob("*.mp4"))
    cache = Path(".cache")
    cache.mkdir(exist_ok=True)
    all_p = list(combos())
    print(f"영상 {len(clips)}개, 조합 {len(all_p)}개")

    rows = []
    for model in args.models:
        data = {}
        for c in clips:
            print(f"  검출 {model} {c.name} ...", end="", flush=True)
            data[c] = detect_all(c, cfg, model, cache)
            print(" 완료")
        for run_fps in args.fps:
            # 조합 x 영상 결과 표
            table = []
            for p in all_p:
                res = {}
                for c in clips:
                    _, tin, tout = truth_of(c.stem)
                    cin, cout = count(*data[c], run_fps, p, cfg.get("line", {}))
                    res[c.name] = (cin, cout, tin, tout)
                ok = sum((r[0], r[1]) == (r[2], r[3]) for r in res.values())
                err = sum(abs(r[0] - r[2]) + abs(r[1] - r[3]) for r in res.values())
                table.append((ok, -err, p, res))
                rows.append({"model": model, "fps": run_fps, **p, "correct": ok, "error": err,
                             **{n: f"{r[0]}/{r[1]}" for n, r in res.items()}})
            table.sort(key=lambda x: (x[0], x[1]), reverse=True)
            best = table[0][0]
            n_best = sum(1 for t in table if t[0] == best)
            print(f"\n=== {model}, 초당 {run_fps:g}장: 최고 {best}/{len(clips)} (이 점수 조합 {n_best}개/{len(table)}) ===")
            for ok, nerr, p, res in table[:args.top]:
                print(f"  {ok}/{len(clips)} 오차 {-nerr}  " + " ".join(f"{k}={v}" for k, v in p.items()))
            # 하나 빼고 검증: 나머지로 고른 최선 조합이 빠진 영상을 맞히는지
            loo = 0
            for c in clips:
                rest = sorted(table, key=lambda x: (
                    sum((r[0], r[1]) == (r[2], r[3]) for n, r in x[3].items() if n != c.name),
                    -sum(abs(r[0] - r[2]) + abs(r[1] - r[3]) for n, r in x[3].items() if n != c.name)),
                    reverse=True)[0]
                r = rest[3][c.name]
                loo += (r[0], r[1]) == (r[2], r[3])
            print(f"  하나 빼고 검증: {loo}/{len(clips)}  (처음 보는 영상에서 기대할 수 있는 정확도)")

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"\n전체 결과: {args.out}")


if __name__ == "__main__":
    main()
