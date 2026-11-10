"""중심점 거리로 사람을 프레임 사이에 이어 붙인다(ID 유지).

프레임마다 '이전 사람들'과 '새 상자들'의 중심점 거리를 모두 재고,
가까운 쌍부터 짝지어 같은 사람으로 본다. 짝이 없는 상자는 새 사람,
일정 시간 안 보인 사람은 지운다.
"""
import math


class Track:
    def __init__(self, track_id, box, t):
        self.id = track_id
        self.box = box                 # (x1, y1, x2, y2, score)
        self.center = center(box)
        self.prev_center = None
        self.velocity = (0.0, 0.0)     # 초당 이동량(px/s)
        self.first_seen = self.last_seen = t
        self.best_shot = None          # 2단계 얼굴 인식용: 가장 잘 나온 한 장
        self.best_score = -1.0


    def predict(self, t):
        """지금 속도로 계속 걸었다면 시각 t 에 있을 위치."""
        dt = t - self.last_seen
        return (self.center[0] + self.velocity[0] * dt, self.center[1] + self.velocity[1] * dt)


def center(box):
    x1, y1, x2, y2 = box[:4]
    return ((x1 + x2) / 2, (y1 + y2) / 2)


class CentroidTracker:
    """max_dist: 한 프레임 사이 같은 사람으로 볼 최대 이동 거리(px)
    max_age: 이 시간(초) 동안 안 보이면 사라진 것으로 본다
    """

    def __init__(self, max_dist=160, max_age=1.0):
        self.max_dist = max_dist
        self.max_age = max_age
        self.tracks = {}
        self._next_id = 1

    def update(self, boxes, t, frame=None):
        """boxes: 이번 프레임의 사람 상자들, t: 시각(초). 지금 보이는 Track 목록을 돌려준다."""
        # 1. 모든 (사람, 상자) 쌍의 거리를 재서 가까운 순으로 짝짓기.
        #    거리는 '지금 위치'가 아니라 '걷던 속도로 예상한 위치'에서 잰다.
        #    나란히 걷는 두 사람이 서로 바뀌거나, 잠깐 놓친 사람을 새 사람으로 보는 걸 줄인다.
        pairs = []
        for tid, tr in self.tracks.items():
            guess = tr.predict(t)
            for i, b in enumerate(boxes):
                d = math.dist(guess, center(b))
                if d <= self.max_dist:
                    pairs.append((d, tid, i))
        pairs.sort()
        used_tracks, used_boxes = set(), set()
        for d, tid, i in pairs:
            if tid in used_tracks or i in used_boxes:
                continue
            used_tracks.add(tid)
            used_boxes.add(i)
            self._move(self.tracks[tid], boxes[i], t, frame)

        # 2. 짝 없는 상자 = 새 사람
        for i, b in enumerate(boxes):
            if i not in used_boxes:
                tr = Track(self._next_id, b, t)
                self._next_id += 1
                self._update_best(tr, b, frame)
                self.tracks[tr.id] = tr
                used_tracks.add(tr.id)

        # 3. 오래 안 보인 사람 지우기
        for tid in [tid for tid, tr in self.tracks.items() if t - tr.last_seen > self.max_age]:
            del self.tracks[tid]

        return [self.tracks[tid] for tid in used_tracks]

    def _move(self, tr, box, t, frame):
        new = center(box)
        dt = t - tr.last_seen
        if dt > 0:
            v = ((new[0] - tr.center[0]) / dt, (new[1] - tr.center[1]) / dt)
            # 갑자기 튀는 값을 줄이려고 이전 속도와 반반 섞는다
            tr.velocity = v if tr.velocity == (0.0, 0.0) else (
                (tr.velocity[0] + v[0]) / 2, (tr.velocity[1] + v[1]) / 2)
        tr.prev_center = tr.center
        tr.center = new
        tr.box = box
        tr.last_seen = t
        self._update_best(tr, box, frame)

    @staticmethod
    def _update_best(tr, box, frame):
        # 크게, 확실하게 찍힌 장면을 베스트로(2단계에서 얼굴 정면 점수로 바꿀 자리)
        x1, y1, x2, y2, score = box
        quality = (x2 - x1) * (y2 - y1) * score
        if frame is not None and quality > tr.best_score:
            tr.best_score = quality
            tr.best_shot = frame[int(y1):int(y2), int(x1):int(x2)].copy()
