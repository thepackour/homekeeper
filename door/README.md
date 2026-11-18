# ① 현관 (door)

Pi 400 + 우노. 우노는 부품만 다루고, 판단은 Pi의 `door_node.py`가 한다. 둘은 USB 시리얼로 연결한다.
서보가 아직 없어서 문 열림은 LCD 글자(`DOOR OPEN`)와 부저로 보여 준다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `door_uno/door_uno.ino` | 우노: LCD, 부저, 나가기 버튼, IR 리모컨, 초음파, 카드 리더 RC522 |
| `door_node.py` | 현관 메인 프로그램 (카드, 비밀번호, 얼굴, 허락, 서성임 → MQTT) |
| `door_setup.py` | 카드와 리모컨 비밀번호 등록 → `door_data.json` (git 제외) |
| `face_watch.py` | 카메라로 얼굴 확인, 방문자 사진 만들기 |
| `loiter.py` | 초음파 거리로 서성임 판단 |
| `uno_link.py`, `fake_uno.py` | 우노 연결 / 우노 없이 키보드로 시험 |
| `enroll.py`, `recognize.py`, `face_common.py` | 얼굴 등록, 확인 (`face_db/`, `models/`는 git 제외) |
| `test_uno.py` | 우노 부품 확인 |

## 처음 한 번

1. 우노: Arduino IDE 라이브러리 관리자에서 `MFRC522`를 설치하고 `door_uno.ino`를 업로드한다.
   LCD 첫 줄에 `RC522 OK 92`처럼 나오면 카드 리더가 연결된 것이다. `RC522 NOT FOUND`면 배선을 확인한다.
2. Pi: 저장소를 받고 필요한 것을 설치한다. `common/`도 같이 있어야 한다.
   ```bash
   git clone https://github.com/thepackour/homekeeper.git
   sudo apt install -y python3-serial python3-opencv
   pip3 install --break-system-packages "paho-mqtt>=2"
   ```
3. `common/secrets.example.json`을 `common/secrets.json`으로 복사하고 door 비밀번호를 넣는다.
4. `door/models/`에 YuNet, SFace 모델(OpenCV Zoo)을 넣는다.
5. 등록 (현관 프로그램이 꺼져 있을 때. 우노 포트를 같이 쓸 수 없음)
   ```bash
   cd homekeeper/door
   python3 enroll.py sihoon             # 얼굴
   python3 door_setup.py card sihoon    # 카드를 리더에 댄다. 이름은 얼굴과 같게
   python3 door_setup.py password       # 리모컨으로 누를 숫자 4~8자리
   python3 door_setup.py list
   ```

## 실행

```bash
python3 door_node.py
```

우노 없이 노트북에서 시험할 때 (`card A1B2C3D4`, `1234`, `ok`, `btn`, `dist 30` 등을 입력):

```bash
python door_node.py --fake --no-camera --broker localhost
```

## 문이 열리는 순서

1. 카드를 댄다. 등록 안 된 카드는 `UNKNOWN CARD`.
2. 카메라가 얼굴을 최대 3초 본다 (카드 대기 직전 3초에 본 얼굴도 인정).
3. 위험 점수를 매긴다 (제안서 7.3).

   | 요소 | 점수 |
   |---|---|
   | 새벽 0~6시 (Pi 시계 기준) | +2 |
   | 얼굴 불일치, 미인식 | +2 |
   | 10분 안에 문 앞 서성임 | +2 |
   | 외출 모드 (`home/state/mode`) | +1 |
   | 비밀번호 오류 1번마다 | +1 |

4. 0~1점은 카드만, 2~3점은 리모컨 비밀번호(숫자 → CONFIRM, DELETE는 한 글자 지움),
   4점 이상이나 경보 중(의심 단계 3)에는 비밀번호 뒤 월패드·폰 허락까지 받는다.
   네트워크가 끊겼으면 점수와 상관없이 비밀번호를 묻는다.
   LCD 첫 줄에 점수가 같이 나온다: `PASSWORD RISK 2`, `WRONG 1/3 RISK 3`, `APPROVAL RISK 4`.
5. 문 열림: LCD `DOOR OPEN RISK 0` 5초 → `DOOR LOCKED`.

- 출입에 성공하면 그 전의 서성임은 본인이었다고 보고 다음 출입 점수에서 뺀다.

- 비밀번호를 3번 틀리면 경보음이 나고 30초 동안 카드를 받지 않는다.
- 나가기 버튼은 언제나 문을 연다.
- 월패드·폰의 출입 허락(`home/cmd/approve {"ok":1}`)은 현관이 직접 듣고 문을 연다. 허브는 기록만 한다.

## MQTT

보내는 것 (`docs/mqtt.md`)

| 토픽 | 언제 | 예시 |
|---|---|---|
| `home/door/auth` | 인증이 끝날 때 | `{"result":"ok","method":"card+pw","face":"match","score":2}` / 실패는 `"result":"fail"` |
| `home/door/open` | 인증이나 원격 허락으로 문이 열릴 때 | `{"state":"open","by":"auth"}`, `{"state":"open","by":"approve"}` |
| `home/door/exit` | 나가기 버튼 | `{}` |
| `home/door/pwfail` | 비밀번호가 틀릴 때마다 | `{"count":2}` |
| `home/door/loiter` | 서성임 | `{"state":"start"}` → `{"state":"over30"}` → `{"state":"end"}` |
| `home/door/visitor` | 서성임이 시작될 때 | `{"img":"base64"}` (320x240 JPEG, 약 15KB) |

`method`는 `card`, `card+pw`, `card+pw+approve`, `card+approve` 중 하나, `face`는 `match`, `mismatch`, `none` 중 하나.

받는 것: `home/state/mode`, `home/state/suspicion`, `home/state/risk`(`loiter_until`), `home/cmd/approve`

## 바꿀 수 있는 값

| 값 | 지금 | 파일 |
|---|---|---|
| 서성임 거리 / 시작까지 머무는 시간 | 50cm 안 / 5초 | `loiter.py` 맨 위 |
| 떠난 것으로 보는 시간 | 3초 | `loiter.py` |
| 문 열림 시간, 허락 대기, 잠금 시간 | 5초, 60초, 30초 | `door_node.py` 맨 위 |
