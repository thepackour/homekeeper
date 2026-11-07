# broker: Mosquitto 브로커 설정

- 실제(허브, 현관 노드): `common/secrets.json`을 만든 뒤 레포 맨 위에서 `sh broker/setup.sh`. 계정·권한(`homekeeper.acl`)까지 규약대로 설정된다.
- 혼자 테스트: `mosquitto -c broker/test.conf -v` (계정 없이 접속). `common/config.json`의 0번 host를 `localhost`로.
