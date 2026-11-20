#!/bin/bash
# 허브 Pi 점검. 레포 맨 위에서: bash hub/check.sh
cd "$(dirname "$0")/.."
ok()  { echo "  [통과] $1"; }
bad() { echo "  [실패] $1"; FAIL=1; }
FAIL=0
echo "== 홈키파 허브 점검 =="

[ "$(hostname)" = "hub" ] && ok "호스트명 hub" || bad "호스트명이 hub 아님 ($(hostname))"
systemctl is-active --quiet avahi-daemon && ok "hub.local 이름 알림 (avahi)" || bad "avahi-daemon 꺼짐"
systemctl is-active --quiet mosquitto && ok "브로커 실행 중" || bad "브로커 꺼짐 → sudo systemctl start mosquitto"
ss -ltn | grep -q ':1883 ' && ok "1883 포트 (노드용)" || bad "1883 안 열림"
ss -ltn | grep -q ':9001 ' && ok "9001 포트 (웹 화면용 WebSocket)" || bad "9001 안 열림 → sh broker/setup.sh 다시"

if [ -f common/secrets.json ]; then
  HUBPW=$(python3 -c "import json;print(json.load(open('common/secrets.json'))['hub'])")
  ok "common/secrets.json 있음"
else
  bad "common/secrets.json 없음 → 팀 비밀번호 파일 받기"
fi

mosquitto_pub -h localhost -t test -m x 2>/dev/null && bad "계정 없이 접속됨" || ok "계정 없이 접속 거부"

if [ -n "$HUBPW" ] && mosquitto_pub -h localhost -u hub -P "$HUBPW" -t home/status/hub -m '{"alive":1}' 2>/dev/null; then
  ok "hub 계정 접속"
  sleep 1
  A=$(timeout 3 mosquitto_sub -h localhost -u hub -P "$HUBPW" -t home/state/judge -C 1 2>/dev/null)
  echo "$A" | grep -q '"node"' && ok "허브 프로그램 상태 발행 중" || bad "허브 상태 없음 → systemctl status homekeeper-hub"
else
  bad "hub 계정 접속 실패 (secrets.json 비밀번호 확인)"
fi

PORT=$(python3 -c "import json;print(json.load(open('hub/config.json'))['serial'])")
[ -e "$PORT" ] && ok "아두이노 C 포트 $PORT" || bad "아두이노 C 포트 없음 ($PORT)"
id -nG | grep -qw dialout && ok "dialout 그룹" || bad "dialout 그룹 아님 → sudo usermod -aG dialout \$USER 후 재로그인"

TOPIC=$(python3 -c "import json;print(json.load(open('hub/hub_secret.json')).get('ntfy_topic',''))" 2>/dev/null)
if [ -n "$TOPIC" ] && [ "$TOPIC" != "homekeeper-여기에-랜덤문자열-12자이상" ]; then
  curl -s -m 5 -o /dev/null https://ntfy.sh && ok "ntfy 토픽, 인터넷" || bad "인터넷 안 됨 (핫스팟 데이터 확인)"
else
  bad "hub/hub_secret.json 의 ntfy_topic 비어 있음"
fi

if command -v chronyc >/dev/null; then
  chronyc tracking 2>/dev/null | grep -q "Leap status *: Normal" && ok "시간 동기화" || bad "시간 동기화 안 됨"
else
  bad "chrony 없음 → bash hub/setup_time.sh hub"
fi

echo
[ $FAIL -eq 0 ] && echo "전부 통과" || echo "실패 항목 확인"
