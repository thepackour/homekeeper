#!/bin/sh
# 실제 브로커 설치 (hub, door Pi에서 실행). 레포 맨 위에서: sh broker/setup.sh
# common/secrets.json 의 비밀번호로 계정을 만든다.
set -e
sudo apt install -y mosquitto mosquitto-clients
PW=/etc/mosquitto/homekeeper.passwd
sudo rm -f "$PW"
python3 -c "import json;[print(k,v) for k,v in json.load(open('common/secrets.json')).items()]" |
while read -r user pass; do
  if [ -f "$PW" ]; then sudo mosquitto_passwd -b "$PW" "$user" "$pass"
  else sudo mosquitto_passwd -c -b "$PW" "$user" "$pass"; fi
done
sudo chown mosquitto: "$PW" && sudo chmod 600 "$PW"
sudo cp broker/homekeeper.acl /etc/mosquitto/homekeeper.acl
sudo cp broker/mosquitto.conf /etc/mosquitto/conf.d/homekeeper.conf
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto
echo "브로커 준비 완료"
