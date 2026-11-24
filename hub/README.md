# hub: 홈 허브 (Pi 400, 호스트명 hub)

허브 Pi에는 브로커(주)와 허브 판단 프로그램이 같이 돈다. 규약은 `docs/mqtt.md`.

| 파일 | 내용 |
|---|---|
| `hub.py` | 허브 판단 프로그램 (공통 모듈 `Node("hub")` 사용) |
| `config.json` | 허브 설정 (아두이노 포트, 판단 시간) |
| `hub_secret.example.json` | ntfy 토픽 양식 → `hub_secret.json`으로 복사 (git 금지) |
| `homekeeper-hub.service` | 켜지면 자동 실행 |
| `arduino_c/` | 아두이노 C 펌웨어 (PlatformIO) |
| `check.sh` | 허브 Pi 점검 |
| `mock.sh` | 임시 메시지로 판단 테스트 |
| `setup_time.sh` | 노드 시간 동기화 (chrony) |

## 하는 일

| 받는 토픽 | 동작 |
|---|---|
| `home/door/auth` (ok) | 인증 횟수 +1, 판단 창 22초 |
| `home/door/open` (by auth, approve) | `home/cmd/living/camera` `{"on":1,"sec":10}` 로 거실 카메라 켜기 |
| `home/living/count` | 진입 인원 > 인증 횟수 → 경보 3 (`tailgate`). 아니면 집 안 인원 + |
| 판단 창 안에 거실 결과 없음 | 인증 수만 반영, 의심 단계 1 |
| `home/door/loiter` | start → 1, over30 → 2, end → 0 |
| `home/door/open` (외출 중, 인증 없이) | 30초 안에 인증 없으면 의심 단계 2 |
| `home/living/motion` (외출 중) | 인증 기록 없으면 경보 3 (`intrusion`) |
| `home/cmd/mode` | away 면 30초 외출 준비 후 외출 |
| `home/cmd/dismiss` | 의심 단계 0 |
| `home/cmd/approve` | 기록만 (문은 현관이 직접 엶) |
| `home/status/door`, `living` | 끊기면 의심 단계 1, 폰 알림 |

보내는 것: `home/state/mode`, `occupancy`, `suspicion`, `risk`, `judge` (retain), `home/alert`, `home/cmd/living/camera`.

- 외출 준비 30초 동안은 `home/state/mode` 가 `{"mode":"away","until":<끝나는 시각>}` (until 이 지나면 외출 시작)
- `home/state/suspicion` 에 원인 `reason` 이 같이 감 (예: `"tailgate"`, `"loiter"`)
- 허브를 껐다 켜면 브로커에 남은 retain 상태로 복구

## 설치 (허브 Pi, 레포 맨 위에서)

```bash
cp common/secrets.example.json common/secrets.json   # 팀 비밀번호 채우기
sh broker/setup.sh                                    # 브로커 (1883 + 9001, 계정, ACL)
cp hub/hub_secret.example.json hub/hub_secret.json    # ntfy 토픽 채우기
python3 -m venv ~/hk-venv && ~/hk-venv/bin/pip install paho-mqtt pyserial
sudo usermod -aG dialout $USER                        # 다시 로그인
sudo cp hub/homekeeper-hub.service /etc/systemd/system/
sudo systemctl enable --now homekeeper-hub
bash hub/setup_time.sh hub
bash hub/check.sh
```

다른 Pi(door, living, wallpad)의 시간 맞추기: `bash hub/setup_time.sh node`

## 테스트

```bash
bash hub/mock.sh watch      # 터미널 하나
bash hub/mock.sh tailgate   # 경보 3 → 아두이노 C S3, 폰 알림
bash hub/mock.sh dismiss
```

혼자 테스트할 때는 `BROKER=localhost`.

## 아두이노 C

| 부품 | 우노 |
|---|---|
| 초록 LED (정상) | D5 → 220Ω |
| 빨간 LED (경보) | D6 → 220Ω |
| 부저 | D7 |

Pi → 아두이노: `S0` 정상 / `S1` 주의 / `S2` 경고 (빨강 깜빡, 짧게 삑) / `S3` 경보 (빨강 빠르게, 부저) / `T` 테스트
