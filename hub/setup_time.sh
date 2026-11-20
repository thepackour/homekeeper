#!/bin/bash
# 노드끼리 시간 맞추기 (chrony)
# 허브 Pi: 인터넷 시간을 받아서 다른 노드에게 나눠 줌. 인터넷이 끊겨도 허브 시간 기준으로 맞춤
# 다른 Pi: 허브 시간을 먼저 따름
# 사용
#   허브 Pi:   bash hub/setup_time.sh hub
#   다른 Pi:   bash hub/setup_time.sh node
set -e
ROLE="$1"
if [ "$ROLE" != "hub" ] && [ "$ROLE" != "node" ]; then
  echo "사용: bash hub/setup_time.sh hub|node"; exit 1
fi

sudo apt-get install -y chrony
CONF=/etc/chrony/conf.d/homekeeper.conf
sudo mkdir -p /etc/chrony/conf.d

if [ "$ROLE" = "hub" ]; then
  sudo tee "$CONF" >/dev/null <<'EOF'
# 홈키파 허브: 핫스팟 안의 노드에게 시간 제공
allow 172.16.0.0/12
allow 192.168.0.0/16
allow 10.0.0.0/8
# 인터넷 시간을 못 받아도 허브 시계를 기준으로 계속 제공
local stratum 10
EOF
else
  sudo tee "$CONF" >/dev/null <<'EOF'
# 홈키파 노드: 허브 시간을 먼저 따름 (인터넷 시간은 기본 설정 그대로 예비)
server hub.local iburst prefer
# 부팅 직후 시간이 많이 틀려도 바로 맞춤
makestep 1 3
EOF
fi

# conf.d를 읽도록 (대부분 기본으로 들어 있음)
grep -q "confdir /etc/chrony/conf.d" /etc/chrony/chrony.conf || \
  echo "confdir /etc/chrony/conf.d" | sudo tee -a /etc/chrony/chrony.conf >/dev/null

sudo systemctl enable chrony
sudo systemctl restart chrony
sleep 3
chronyc sources
echo "시간 설정 완료 ($ROLE)"
