# homekeeper Copilot 지침
- PR 제목, 설명, 커밋 메시지, 코드 리뷰 코멘트는 한국어로 작성한다.
- PR 본문은 템플릿에 맞게 작성한다.
- Python 3, Raspberry Pi OS 기준. 노드 코드는 common/mqtt_node.py의 Node를 사용하고 paho-mqtt를 직접 쓰지 않는다.
- MQTT 토픽과 메시지 형식은 docs/mqtt.md 규약을 따른다. 규약에 없는 토픽을 만들지 않는다.
- 브로커 주소, 비밀번호를 코드에 직접 쓰지 않는다(common/config.json, secrets.json 사용).
- 주석은 한국어로 짧게 쓴다.
