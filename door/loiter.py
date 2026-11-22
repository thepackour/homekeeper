"""문 앞 서성임 판단. 우노가 0.3초마다 보내는 거리(cm)만 보고 시작 / 30초 넘음 / 끝을 알려 준다."""

NEAR_CM = 50          # 이 거리 안에 있으면 "문 앞에 있음"
START_SEC = 5         # 이만큼 계속 있으면 서성임 시작
LONG_SEC = 30         # 제안서: 서성임 30초 이상이면 의심 단계 2
LEAVE_SEC = 3         # 이만큼 안 보이면 떠난 것으로 본다 (초음파가 가끔 놓쳐서 여유를 둠)


class LoiterWatch:
    def __init__(self, near_cm=NEAR_CM, start_sec=START_SEC, long_sec=LONG_SEC, leave_sec=LEAVE_SEC):
        self.near_cm = near_cm
        self.start_sec = start_sec
        self.long_sec = long_sec
        self.leave_sec = leave_sec
        self.near_since = None   # 문 앞에 온 시각
        self.last_near = None    # 마지막으로 가까이 잰 시각
        self.state = None        # None / "start" / "over30"
        self.last_start = None   # 마지막 서성임 시작 시각 (위험 점수용)
        self.forgiven = False    # 지금 이어지는 서성임은 본인 인증으로 점수에서 뺐음

    @property
    def active(self):
        return self.state is not None

    def update(self, distance, now):
        """거리 하나를 넣으면 보낼 일이 있을 때 "start" / "over30" / "end"를 돌려준다."""
        if 0 <= distance <= self.near_cm:
            self.last_near = now
            if self.near_since is None:
                self.near_since = now
        elif self.last_near is not None and now - self.last_near >= self.leave_sec:
            was_active = self.active
            self.near_since = self.last_near = self.state = None
            return "end" if was_active else None

        if self.near_since is None:
            return None
        stayed = self.last_near - self.near_since  # 떠난 뒤 기다리는 동안은 늘지 않게 마지막으로 본 때까지만
        if self.state is None and stayed >= self.start_sec:
            self.state = "start"
            self.last_start = now
            self.forgiven = False
            return "start"
        if self.state == "start" and stayed >= self.long_sec:
            self.state = "over30"
            return "over30"
        return None

    def hold(self, now):
        """카드 인증 중이거나 문이 열려 있을 때. 그동안은 서성임 시간을 세지 않는다."""
        self.near_since = None
        if self.last_near is not None:
            self.last_near = now

    def recent(self, now, memory_sec):
        """지금 서성이는 중이거나 memory_sec 안에 서성임이 있었으면 True."""
        if self.active and not self.forgiven:
            return True
        return self.last_start is not None and now - self.last_start < memory_sec

    def forget(self):
        """출입에 성공하면 앞서 있던 서성임은 본인이었다고 보고 위험 점수에서 뺀다.
        지금 서성임이 이어지는 중이어도 떠날 때 "end"는 그대로 보낸다."""
        self.last_start = None
        self.forgiven = self.active
