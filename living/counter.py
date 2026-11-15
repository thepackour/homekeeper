"""세로 가상선을 넘는 사람을 센다.

선 양옆에 margin 만큼 띠를 두고, 띠 밖 한쪽에서 띠 밖 반대쪽으로 넘어갔을 때만 센다.
선 위에서 흔들리는 사람을 여러 번 세지 않기 위해서다.

가림 보정: 옆에서 보면 나란히 걷는 두 사람 중 뒷사람이 앞사람에 완전히 가려져
선을 넘은 '뒤에야' 처음 보이는 경우가 있다. 그래서 다음 조건을 모두 만족하는
새 사람은 '가려진 채 선을 넘은 사람'으로 보고 센다.
  - 선을 넘은 쪽에서, 선에서 emerge_zone 안쪽에 처음 나타남(화면 가장자리에서 들어온 게 아님)
  - 나타난 순간 바로 옆(near)에 다른 사람이 있고, 그 사람도 같은 방향으로 걷는 중(같이 넘어옴)
  - 이후 confirm_sec 동안 반대 방향으로 margin 이상 되돌아가지 않음
    (한 프레임 속도만 보면 흔들려서, 나타난 위치에서 얼마나 움직였는지로 본다.
     다시 가려져 사라져도 되돌아간 게 아니면 센다)

다시 나타남: 선 근처에 서 있던 사람이 지나가는 사람에게 잠깐 가려졌다 다시 보이면 추적기는
새 ID 를 준다. 그래서 새 사람이 나타나면 먼저 memory_sec 안에 사라진 사람 중 그 근처(near)에
있던 사람을 찾고, 있으면 같은 사람으로 보고 그 사람이 있던 쪽을 이어받는다.
(같은 쪽이면 세지 않고, 가려진 사이 반대쪽으로 넘어갔으면 한 번 센다)
"""
from living.detector import make_detector
from living.tracker import CentroidTracker

OUTSIDE, INSIDE = "outside", "inside"


class LineCounter:
    """x: 선 위치(화면 너비 비율 0~1)
    in_dir: 들어오는 방향. "right" = 화면 왼쪽(현관)에서 오른쪽(거실)으로 넘으면 들어옴
    margin: 선 양옆 띠 폭(화면 너비 비율)
    """

    def __init__(self, width, x=0.5, in_dir="right", margin=0.03, emerge_zone=0.3, near=0.15,
                 confirm_sec=0.6, memory_sec=5.0):
        self.line_x = x * width
        self.emerge_zone = emerge_zone * width
        self.near = near * width
        self.confirm_sec = confirm_sec
        self.memory_sec = memory_sec
        self.last = {}          # track id -> (마지막 x, x 속도, 마지막 본 시각)
        self.merged = set()     # 다른 ID 로 이어받아진 옛 ID(다시 나타나도 무시)
        self.pending = {}       # 가려졌다 나타난 사람 id -> (예상 방향 "in"|"out", 나타난 x, 나타난 시각)
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

    def update(self, tracks, t=None):
        """보이는 사람들로 계수를 갱신한다. t: 지금 시각(초, 없으면 추적 시각으로).
        이번에 생긴 이벤트 [("in"|"out", id)] 를 돌려준다."""
        events = []
        if t is None:
            t = max((tr.last_seen for tr in tracks), default=None)
        tracks = [tr for tr in tracks if tr.id not in self.merged]
        visible = {tr.id: tr for tr in tracks}
        for tid in list(self.pending):
            self._check_pending(tid, visible.get(tid), t, events)
        for tr in tracks:
            if tr.id not in self.last and tr.id not in self.side:
                self._match_lost(tr, visible, t)     # 처음 보는 ID: 가려졌던 사람인지
            if t is not None:
                self.last[tr.id] = (tr.center[0], tr.velocity[0], t)
        for tr in tracks:
            if tr.id in self.pending:
                continue
            now = self._side_of(tr.center[0])
            if now is None:
                continue
            known = tr.id in self.side
            before = self.side.get(tr.id)
            self.side[tr.id] = now
            if before is None:
                if not known:
                    self._check_emerged(tr, now, tracks)
                continue
            if before == now:
                continue
            self._add("in" if now == INSIDE else "out", tr.id, events)
        return events

    def _match_lost(self, tr, visible, t):
        """최근 사라진 사람 중 이 자리에 있던 사람을 찾아 그 쪽(side)을 이어받는다."""
        if t is None:
            return
        best, best_d = None, self.near
        for tid, (x, vx, seen) in self.last.items():
            if tid in visible or not 0 < t - seen <= self.memory_sec:
                continue
            guess = x + vx * (t - seen)
            d = min(abs(tr.center[0] - x), abs(tr.center[0] - guess))
            if d <= best_d:
                best, best_d = tid, d
        if best is None:
            return
        del self.last[best]                       # 한 사람은 한 번만 이어받음
        self.merged.add(best)
        if best in self.side:
            self.side[tr.id] = self.side[best]
        else:
            self.side[tr.id] = None               # 쪽을 몰라도 '새로 나타난 사람'으로 보지 않음

    def _add(self, kind, tid, events):
        if kind == "in":
            self.count_in += 1
            self.in_ids.append(tid)
        else:
            self.count_out += 1
        events.append((kind, tid))

    def _direction(self, dx):
        """x 이동량의 방향: "in" | "out" """
        return "in" if (dx > 0) == (self.in_dir == "right") else "out"

    def _check_pending(self, tid, tr, t, events):
        kind, x0, t0 = self.pending[tid]
        if tr is not None:
            dx = tr.center[0] - x0
            if abs(dx) >= self.margin and self._direction(dx) != kind:
                del self.pending[tid]           # 되돌아감: 선을 넘은 사람이 아님
                return
        if tr is None or t is None or t - t0 >= self.confirm_sec:
            del self.pending[tid]               # 시간이 지났거나 다시 가려짐: 센다
            self._add(kind, tid, events)
            if tr is not None:
                self.side[tid] = INSIDE if kind == "in" else OUTSIDE

    def _check_emerged(self, tr, side, tracks):
        if abs(tr.center[0] - self.line_x) > self.emerge_zone:
            return
        kind = "in" if side == INSIDE else "out"
        for o in tracks:
            if o is tr or abs(o.center[0] - tr.center[0]) > self.near:
                continue
            if abs(o.velocity[0]) > 1e-6 and self._direction(o.velocity[0]) == kind:
                self.pending[tr.id] = (kind, tr.center[0], tr.first_seen)
                return

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
                                near=lc.get("near", 0.15), confirm_sec=lc.get("confirm_sec", 0.6),
                                memory_sec=lc.get("memory_sec", 5.0))
        self.entered = {}

    def process(self, frame, t):
        """프레임 하나 처리. (사람 상자들, 보이는 Track들, 이벤트들)"""
        boxes = self.detector.detect(frame)
        tracks = self.tracker.update(boxes, t, frame)
        events = self.line.update(tracks, t)
        for kind, tid in events:
            if kind == "in":
                self.entered[tid] = self.tracker.tracks[tid]   # 사라져도 베스트샷은 남게
        return boxes, tracks, events

    def result(self):
        return self.line.result()

    def best_shots(self):
        """들어온 사람별 베스트샷 {id: 이미지}. 꼬리물기 경보 때 snapshot 으로 보낸다."""
        return {i: tr.best_shot for i, tr in self.entered.items() if tr.best_shot is not None}
