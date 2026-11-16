// 홈키파 화면 설정.
// 토픽과 메시지 모양은 팀 저장소 docs/mqtt.md 규약을 그대로 따른다. 규약에 없는 토픽은 만들지 않는다.

// 브로커 주소는 코드에 적지 않고 저장소 common/config.json 에서 가져온다(vite.config.js 가 빌드할 때 넣어 줌).
// 0번 주 = 허브, 1번 예비 = 현관. 이름(host)만 쓰고, 화면은 WebSocket 이라 포트는 1883 대신 WS_PORT.
// 파일이 없으면(저장소 밖) 빈칸이고, 로그인 화면에서 직접 넣는다. 바꾼 값은 그 기기에만 저장된다.
/* global __COMMON_CONFIG__ */
const common = __COMMON_CONFIG__ ?? {}
export const DEFAULT_BROKERS = [0, 1].map((i) => common.brokers?.[i]?.host ?? '')
export const WS_PORT = 9001 // broker/mosquitto.conf 의 WebSocket 리스너

// 주 브로커가 이만큼 끊기면 예비로 넘어간다. 자동으로 돌아가지 않음(공통 모듈과 같음)
export const FAILOVER_SEC = common.failover_sec ?? 3
export const HEARTBEAT_SEC = common.heartbeat_sec ?? 1 // 월패드 살아 있음 신호 주기
export const STALE_SEC = 3 // 노드 살아 있음 신호가 이만큼 안 오면 '응답 없음'

// 로그인 계정 (broker/homekeeper.acl 에서 명령을 보낼 수 있는 둘)
export const ACCOUNTS = [
  { key: 'wallpad', label: '월패드' },
  { key: 'phone', label: '폰' },
]

export const TOPICS = {
  // 받는 것 (허브, 현관이 보냄)
  mode: 'home/state/mode', // {"mode":"home|away|sleep"} retain
  occupancy: 'home/state/occupancy', // {"n":2} retain, 집 안 인원
  suspicion: 'home/state/suspicion', // {"level":0~3} retain, 의심 단계
  judge: 'home/state/judge', // {"node":"hub"} retain, 지금 판단하는 노드
  alert: 'home/alert', // {"level":3,"type":"tailgate"} retain 아님
  doorOpen: 'home/door/open', // {"state":"open","by":"auth"}
  doorLoiter: 'home/door/loiter', // {"state":"start"} → {"state":"over30"} → {"state":"end"}
  doorVisitor: 'home/door/visitor', // {"img":"base64"} 방문자 사진
  status: 'home/status/+', // {"alive":1} 1초마다, 끊기면 LWT {"alive":0}

  // 보내는 것 (월패드, 폰만 보낼 수 있음. QoS 1)
  cmdMode: 'home/cmd/mode', // {"mode":"away"}
  cmdApprove: 'home/cmd/approve', // {"ok":1} 출입 허락. 현관이 직접 듣고 문을 연다
  cmdDismiss: 'home/cmd/dismiss', // {} 경보 해제
}

export const statusTopic = (node) => `home/status/${node}`

// 살아 있음을 보내는 노드 (규약 '살아 있음' 표). 폰은 목록에 없어서 보내지 않는다.
export const NODES = [
  { key: 'door', label: '현관' },
  { key: 'living', label: '거실' },
  { key: 'hub', label: '허브' },
  { key: 'wallpad', label: '월패드' },
]

export const MODES = [
  { key: 'home', label: '재택' },
  { key: 'away', label: '외출' },
  { key: 'sleep', label: '취침' },
]

// 의심 단계 0~3 (제안서 기준)
export const LEVELS = [
  { cls: 'ok', title: '정상', note: '이상 없음' },
  { cls: 'watch', title: '주의', note: '문 앞에 누가 서성이고 있어요. 현관 칸에서 방문자 사진을 확인하세요.' },
  { cls: 'warn', title: '경고', note: '문 앞에 30초 넘게 머물고 있거나, 외출 중 문이 열린 뒤 30초 안에 인증이 없었어요.' },
  { cls: 'alarm', title: '경보', note: '꼬리물기가 감지됐어요. 집 전체에 경보가 울리고 있어요.' },
]
export const DISMISS_FROM = 2 // 이 단계부터 '경보 해제' 버튼을 보여 준다

// 허브가 보내는 값을 한국어로. 모르는 값은 받은 글자 그대로 보여 준다.
export const ALERT_TYPES = { tailgate: '꼬리물기' }
export const DOOR_BY = { auth: '인증', approve: '원격 허락' }
export const LOITER = {
  start: '문 앞에 사람 있음',
  over30: '30초 넘게 서성임',
  end: '문 앞 비어 있음',
}

export const label = (list, key) => list.find((x) => x.key === key)?.label ?? key
