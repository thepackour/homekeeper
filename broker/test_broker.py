"""혼자 테스트용 MQTT 브로커 (Mosquitto 설치 없이 파이썬만으로).

    pip install amqtt
    python broker/test_broker.py            # 1883 포트
    python broker/test_broker.py 1884       # 예비 브로커 흉내(포트 다르게)

계정 없이 접속된다. common/config.json 의 host 를 localhost 로 바꿔서 쓴다.
"""
import asyncio
import sys

from amqtt.broker import Broker

port = int(sys.argv[1]) if len(sys.argv) > 1 else 1883

config = {
    "listeners": {"default": {"type": "tcp", "bind": f"0.0.0.0:{port}"}},
    "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
}


async def main():
    broker = Broker(config)
    await broker.start()
    print(f"테스트 브로커 실행 중: localhost:{port} (Ctrl+C로 종료)")
    await asyncio.Event().wait()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
