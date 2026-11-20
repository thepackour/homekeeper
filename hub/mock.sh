#!/bin/bash
# 다른 노드 없이 임시 메시지로 허브 판단 테스트. 레포 맨 위에서: bash hub/mock.sh <시나리오>
# 비밀번호는 common/secrets.json 에서 읽음. 브로커: BROKER (기본 hub.local)
#   watch     전체 메시지 보기 (다른 터미널에 띄워 두기)
#   normal    정상 귀가 (인증 1, 진입 1)
#   tailgate  꼬리물기 (인증 1, 진입 2)
#   group     세 명 각자 인증 (인증 3, 진입 3)
#   loiter    문 앞 서성임 → 30초 초과 → 떠남
#   exit      나가기 버튼
#   away      외출 모드 (30초 준비 후 외출)
#   intrude   외출 중 거실 움직임
#   dismiss   경보 해제
#   lost      거실 노드 끊김 → 복귀
H=${BROKER:-hub.local}
pw() { python3 -c "import json;print(json.load(open('common/secrets.json'))['$1'])"; }
door()   { mosquitto_pub -h $H -u door   -P "$(pw door)"   -q 1 -t "$1" -m "$2"; }
living() { mosquitto_pub -h $H -u living -P "$(pw living)" -q 1 -t "$1" -m "$2"; }
phone()  { mosquitto_pub -h $H -u phone  -P "$(pw phone)"  -q 1 -t "$1" -m "$2"; }
T() { date +%s; }

case "$1" in
  watch)    mosquitto_sub -h $H -u hub -P "$(pw hub)" -t 'home/#' -v ;;
  normal)
    door home/door/auth "{\"result\":\"ok\",\"method\":\"card\",\"face\":\"match\",\"score\":0,\"t\":$(T)}"
    door home/door/open "{\"state\":\"open\",\"by\":\"auth\",\"t\":$(T)}"
    sleep 3; living home/living/count "{\"count\":1,\"t\":$(T)}" ;;
  tailgate)
    door home/door/auth "{\"result\":\"ok\",\"method\":\"card\",\"face\":\"match\",\"score\":0,\"t\":$(T)}"
    door home/door/open "{\"state\":\"open\",\"by\":\"auth\",\"t\":$(T)}"
    sleep 3; living home/living/count "{\"count\":2,\"t\":$(T)}" ;;
  group)
    for i in 1 2 3; do
      door home/door/auth "{\"result\":\"ok\",\"method\":\"card\",\"face\":\"match\",\"score\":0,\"t\":$(T)}"; sleep 1
    done
    door home/door/open "{\"state\":\"open\",\"by\":\"auth\",\"t\":$(T)}"
    sleep 2; living home/living/count "{\"count\":3,\"t\":$(T)}" ;;
  loiter)
    door home/door/loiter "{\"state\":\"start\",\"t\":$(T)}"; sleep 2
    door home/door/loiter "{\"state\":\"over30\",\"t\":$(T)}"; sleep 2
    door home/door/loiter "{\"state\":\"end\",\"t\":$(T)}" ;;
  exit)     door home/door/exit "{\"t\":$(T)}" ;;
  away)     phone home/cmd/mode "{\"mode\":\"away\",\"t\":$(T)}" ;;
  home)     phone home/cmd/mode "{\"mode\":\"home\",\"t\":$(T)}" ;;
  intrude)  living home/living/motion "{\"state\":1,\"t\":$(T)}" ;;
  dismiss)  phone home/cmd/dismiss "{\"t\":$(T)}" ;;
  lost)
    living home/status/living '{"alive":0}'; sleep 2
    living home/status/living '{"alive":1}' ;;
  *) sed -n '2,15p' "$0" ;;
esac
