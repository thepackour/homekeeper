"""세로 가상선을 넘는 사람을 센다.

선 양옆에 margin 만큼 띠를 두고, 띠 밖 한쪽에서 띠 밖 반대쪽으로 넘어갔을 때만 센다.
선 위에서 흔들리는 사람을 여러 번 세지 않기 위해서다.

가림 보정: 옆에서 보면 나란히 걷는 두 사람 중 뒷사람이 앞사람에 완전히 가려져
선을 넘은 '뒤에야' 처음 보이는 경우가 있다. 그래서 다음 조건을 모두 만족하는
새 사람은 '가려진 채 선을 넘은 사람'으로 보고 센다.
  - 선을 넘은 쪽에서, 선에서 emerge_zone 안쪽에 처음 나타남(화면 가장자리에서 들어온 게 아님)
  - 나타난 순간 바로 옆(near)에 다른 사람이 있음(그 사람에게 가려져 있었음)
  - 다음 프레임에 그 방향으로 계속 움직임
"""
from living.detector import make_detector
from living.tracker import CentroidTracker

OUTSIDE, INSIDE = "outside", "inside"


class LineCounter:
    """x: 선 위치(화면 너비 비율 0~1)
    in_dir: 들어오는 방향. "right" = 화면 왼쪽(현관)에서 오른쪽(거실)으로 넘으면 들어옴
    margin: 선 양옆 띠 폭(화면 너비 비율)
    """

    def __init__(self, width, x=0.5, in_dir="right", margin=0.03, emerge_zone=0.3, near=0.15):
        self.line_x = x * width
        self.emerge_zone = emerge_zone * width
        self.near = near * width
        self.pending = {}       # 가려졌다 나타난 사람 id -> 예상 방향("in"|"out")
        self.margin = margin * width
        self.in_dir = in_dir
        self.side = {}          # track id -> 마지막으로 확실했던 쪽
        self.count_in = 0
        self.count_out = 0
        self.in_ids = []        # 들어온 사람 id(순서대로)

    def _side_of(self, cx):
        if abs(cx - self.line_x) <= self.margin:
            return None         # 띠 안: 아직 판단 보류
        right = cx > self.line_x
        return INSIDE if right == (self.in_dir == "right") else OUTSIDE

    def update(self, tracks):
        """보이는 사람들로 계수를 갱신한다. 이번에 생긴 이벤트 [("in"|"out", id)] 를 돌려준다."""
        events = []
        for tr in tracks:
            # 가려졌다 나타난 사람: 그 방향으로 계속 가면 센다
            if tr.id in self.pending:
                kind = self.pending.pop(tr.id)
                if self._moving(tr) == kind:
                    self._add(kind, tr.id, events)
                continue
            now = self._side_of(tr.center[0])
            if now is None:
                continue
            before = self.side.get(tr.id)
            self.side[tr.id] = now
            if before is None:
                self._check_emerged(tr, now, tracks)
                continue
            if before == now:
                continue
            self._add("in" if now == INSIDE else "out", tr.id, events)
        return events

    def _add(self, kind, tid, events):
        if kind == "in":
            self.count_in += 1
            self.in_ids.append(tid)
        else:
            self.count_out += 1
        events.append((kind, tid))

    def _moving(self, tr):
        vx = tr.velocity[0]
        if abs(vx) < 1e-6:
            return None
        return "in" if (vx > 0) == (self.in_dir == "right") else "out"

    def _check_emerged(self, tr, side, tracks):
        if abs(tr.center[0] - self.line_x) > self.emerge_zone:
            return
        if not any(o is not tr and abs(o.center[0] - tr.center[0]) <= self.near for o in tracks):
            return
        self.pending[tr.id] = "in" if side == INSIDE else "out"

    def result(self):
        return {"count": self.count_in, "out": self.count_out,
                "people": [{"id": i, "face": None} for i in self.in_ids]}


class PeopleCounter:
    """검출 → 추적 → 선 넘기를 한 번에. 창(10초) 하나마다 새로 만든다."""

    def __init__(self, cfg, width, detector=None):
        self.detector = detector or make_detector(cfg["detector"])
        tc, lc = cfg.get("tracker", {}), cfg.get("line", {})
        self.tracker = CentroidTracker(max_dist=tc.get("max_dist", 0.25) * width,
                                       max_age=tc.get("max_age", 1.0))
        self.line = LineCounter(width, x=lc.get("x", 0.5), in_dir=lc.get("in_dir", "right"),
                                margin=lc.get("margin", 0.03), emerge_zone=lc.get("emerge_zone", 0.3),
                                near=lc.get("near", 0.15))
        self.entered = {}

    def process(self, frame, t):
        """프레임 하나 처리. (사람 상자들, 보이는 Track들, 이벤트들)"""
        boxes = self.detector.detect(frame)
        tracks = self.tracker.update(boxes, t, frame)
        events = self.line.update(tracks)
        for kind, tid in events:
            if kind == "in":
                self.entered[tid] = self.tracker.tracks[tid]   # 사라져도 베스트샷은 남게
        return boxes, tracks, events

    def result(self):
        return self.line.result()

    def best_shots(self):
        """들어온 사람별 베스트샷 {id: 이미지}. 꼬리물기 경보 때 snapshot 으로 보낸다."""
        return {i: tr.best_shot for i, tr in self.entered.items() if tr.best_shot is not None}
