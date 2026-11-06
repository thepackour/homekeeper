# MQTT 규약

## 네트워크
- 휴대폰 핫스팟, 팀원 1명 폰 전용. 인터넷 필요 없음
- 핫스팟 이름, 비밀번호 절대 안 바꾸기
- 자동 끄기 해제, 최대 연결 6대 이상 확인 (Pi 4 + 노트북 + 폰)
- Pi 호스트명: door, living, hub, wallpad
- 주소는 IP 말고 이름으로: hub.local, door.local
- 주소는 common/config.json 한 곳에서만 읽기

## 공통 규칙
- 브로커: 주 hub.local / 예비 door.local, 포트 1883
- 토픽: home/<노드>/<내용>, 소문자
- 메시지: JSON, 모든 메시지에 "t"(보낸 시각) 포함
- QoS: 상태, 경보, 명령은 1 / 살아 있음 신호는 0
- retain: home/state/, home/status/ 만
- 계정: door, living, hub, wallpad, phone (각자 비밀번호)

## 세부 규약

### 살아 있음
| 항목 | 내용 |
|---|---|
| 주기 | 1초마다 |
| LWT | `{"alive":0}` |
| 토픽 | `home/status/door`, `living`, `hub`, `wallpad` |
| 이어받기 | hub 3초 끊기면 door가 이어받음 |

### ① 현관 → 허브
| 토픽 | 내용 | 페이로드 예시 | 비고 |
|---|---|---|---|
| `home/door/auth` | 인증 결과 | `{"result":"ok","method":"card+pw","face":"match","score":3}` | |
| `home/door/open` | 문 열림 | `{"state":"open","by":"auth"}` | |
| `home/door/loiter` | 서성임 | `{"state":"start"}` → `{"state":"over30"}` → `{"state":"end"}` | |
| `home/door/visitor` | 방문자 사진 | `{"img":"base64"}` | |
| `home/door/exit` | 나가기 버튼 | | |
| `home/door/pwfail` | 비밀번호 오류 | `{"count":2}` | |
| `home/door/duress` | 비상 번호 | | 최종 데모 |

### ② 거실 → 허브
| 토픽 | 내용 | 페이로드 예시 |
|---|---|---|
| `home/living/count` | 10초 인원 | `{"count":2}` |
| `home/living/motion` | PIR | `{"state":1}` |
| `home/living/radar` | 방 레이더 | `{"targets":1}` |
| `home/living/snapshot` | 경보 시 사진 | |

### ③ 허브 → 전체(retain)
| 토픽 | 내용 | 페이로드 예시 | 비고 |
|---|---|---|---|
| `home/state/mode` | | `{"mode":"home"}` | home / away / sleep |
| `home/state/occupancy` | 집 안 인원 | `{"n":2}` | |
| `home/state/suspicion` | 의심 단계 | `{"level":0}` | |
| `home/state/risk` | 점수 요소 | `{"away":1,"loiter_until":...}` | |
| `home/state/judge` | 판단 담당 | `{"node":"hub"}` | |
| `home/alert` | 경보 | `{"level":3,"type":"tailgate"}` | retain 아님 |
| `home/cmd/living/camera` | 카메라 켜기 | `{"on":1,"sec":10}` | |

### ④ 월패드, 폰 → 허브 (이 둘만 발행 가능)
| 토픽 | 내용 | 페이로드 예시 |
|---|---|---|
| `home/cmd/mode` | 모드 변경 | `{"mode":"away"}` |
| `home/cmd/approve` | 출입 허락 | `{"ok":1}` |
| `home/cmd/dismiss` | 경보 해제 | |
