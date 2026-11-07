# common: 공통 MQTT 모듈

모든 Pi 노드(현관, 거실, 허브, 월패드)가 같이 쓰는 MQTT 코드. 규약은 `docs/mqtt.md`.

## 준비
```
pip install paho-mqtt        # 2.x
```
- `config.json`: 브로커 주소(0번 주 = hub.local, 1번 예비 = door.local). 주소는 여기서만 고친다.
- `secrets.json`: 노드별 비밀번호. `secrets.example.json`을 복사해서 만든다. **git에 올리지 않는다**(.gitignore).
  파일이 없으면 인증 없이 접속한다(혼자 테스트할 때).

## 쓰는 법
`mqtt_node.py`의 `Node`를 import하여 사용한다.

**`start()`**: 백그라운드로 켜고 바로 다음 줄로 넘어간다. 메인 루프가 따로 있을 때.
```python
from common.mqtt_node import Node

node = Node("living")

@node.on("home/cmd/living/camera")      # 와일드카드(+, #) 가능
def on_camera(msg, topic):               # msg는 dict
    print("카메라", msg.get("sec"))

node.start()
try:
    while True:
        count = count_people()           # 내 처리 코드
        node.publish("home/living/count", {"count": count})   # "t" 자동
finally:
    node.stop()                          # 종료는 직접
```

**`run()`**: 켜고 Ctrl+C까지 그 줄에서 대기한다. 메시지에 반응만 하면 될 때.
```python
from common.mqtt_node import Node

node = Node("living")

@node.on("home/cmd/living/camera")
def on_camera(msg, topic):
    node.publish("home/living/count", {"count": 2})

node.run()                               # 종료 처리까지 알아서
```

## 모듈이 알아서 하는 것
| 항목 | 동작 |
|---|---|
| LWT | `home/status/<이름>`에 `{"alive":0}`, retain |
| 살아 있음 | 1초마다 `{"alive":1}` |
| `"t"` | 보낼 때 자동으로 붙음(유닉스 시각, 초) |
| QoS | `home/status/`는 0, 나머지는 1 |
| retain | `home/state/`, `home/status/`만 자동. 다른 토픽에 retain을 요청하면 오류 |
| 예비 브로커 | 주 브로커가 3초 끊기면 예비로 전환(실측 약 4초) |

## 예비 브로커 규칙
- 한 번 예비로 넘어가면 **자동으로 돌아가지 않는다.** 노드마다 제각각 돌아가 브로커가 둘로 갈라지는 걸 막기 위해서다.
  허브 복구 후 되돌릴 때는 `node.switch_broker(0)`.
- 현관 Pi의 Mosquitto(예비 브로커)는 항상 켜 두는 것을 전제로 한다.
- 전환을 알고 싶으면 `node.on_broker_change = lambda i, b: ...`.
- 이 전환은 "브로커 연결이 끊겼을 때"만 일어난다. 허브 Pi의 판단 프로그램만 죽고 브로커는 살아 있는 경우는
  현관 노드가 `home/status/hub`를 보고 판단을 이어받아야 한다(현관 노드 몫).

## 혼자 테스트
`broker/README.md` 참고.
