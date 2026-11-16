// 브로커 연결 하나를 맡는다. common/mqtt_node.py 와 같은 규칙을 브라우저(mqtt.js)로 옮긴 것.
// - 모든 메시지에 "t"(보낸 시각, 초) 자동
// - QoS: home/status/ 는 0, 나머지(상태, 경보, 명령)는 1
// - retain: home/state/, home/status/ 만
// - 월패드 계정이면 1초마다 home/status/wallpad {"alive":1}, LWT {"alive":0}
// - 주 브로커가 3초 끊기면 예비로 넘어가고, 자동으로 돌아가지 않는다
import mqtt from 'mqtt'
import { FAILOVER_SEC, HEARTBEAT_SEC, TOPICS, WS_PORT, statusTopic } from './config'

const RETAIN_PREFIXES = ['home/state/', 'home/status/']
const QOS0_PREFIXES = ['home/status/']
// 접속 거부 코드 중 '계정, 비밀번호 문제' (MQTT 3.1.1: 4, 5 / MQTT 5: 134, 135)
const AUTH_FAIL_CODES = [4, 5, 134, 135]

const SUBSCRIBE = [
  TOPICS.mode,
  TOPICS.occupancy,
  TOPICS.suspicion,
  TOPICS.judge,
  TOPICS.alert,
  TOPICS.doorOpen,
  TOPICS.doorLoiter,
  TOPICS.doorVisitor,
  TOPICS.status,
]

const decoder = new TextDecoder()

export const nowSec = () => Date.now() / 1000 // 밀리초 단위라 소수 3자리

// 'hub.local' → 'ws://hub.local:9001'. 'localhost:9002', 'ws://...' 도 받는다.
export function wsUrl(addr) {
  const m = /^(wss?:\/\/)?([^/:\s]+)(?::(\d+))?(\/\S*)?$/.exec(String(addr ?? '').trim())
  if (!m) return null
  return `${m[1] ?? 'ws://'}${m[2]}:${m[3] ?? WS_PORT}${m[4] ?? ''}`
}

export class Link {
  // brokers: [주, 예비] 주소. on.conn(상태, 브로커 번호), on.message(토픽, 객체, retain 여부)
  constructor({ user, password, brokers, on }) {
    this.user = user
    this.password = password
    this.brokers = brokers.filter(Boolean)
    this.on = on
    this.index = 0 // 0 = 주(허브), 1 = 예비(현관)
    this.client = null
    this.connected = false
    this.stopped = false
    this.lostAt = Date.now() // 처음엔 '끊긴 상태'에서 시작 (공통 모듈과 같음)
  }

  get sendsHeartbeat() {
    return this.user === 'wallpad'
  }

  start() {
    this.connect(0)
    this.watchTimer = setInterval(() => this.watch(), 500)
    this.beatTimer = setInterval(() => {
      if (this.sendsHeartbeat) this.publish(statusTopic(this.user), { alive: 1 })
    }, HEARTBEAT_SEC * 1000)
  }

  stop() {
    this.stopped = true
    clearInterval(this.watchTimer)
    clearInterval(this.beatTimer)
    const client = this.client
    this.client = null
    if (!client) return
    if (!this.connected) {
      // 아직 접속 중이면 바로 끊는다 (기다리면 반쯤 열린 연결이 남아 나중에 LWT 가 나감)
      client.end(true)
      return
    }
    // 정상 종료(로그아웃 등)는 LWT 가 나가지 않으므로 직접 알린다
    if (this.sendsHeartbeat) {
      client.publish(statusTopic(this.user), JSON.stringify({ alive: 0, t: nowSec() }), { qos: 1, retain: true })
    }
    client.end(false)
  }

  // 브로커를 직접 바꾼다. 예비로 넘어간 뒤 주 브로커로 되돌릴 때 사용
  switchBroker(index) {
    if (this.stopped || !this.brokers[index]) return
    this.connect(index)
  }

  publish(topic, data, done) {
    if (!this.connected) return false
    const body = { ...data, t: nowSec() }
    const qos = QOS0_PREFIXES.some((p) => topic.startsWith(p)) ? 0 : 1
    const retain = RETAIN_PREFIXES.some((p) => topic.startsWith(p))
    this.client.publish(topic, JSON.stringify(body), { qos, retain }, done)
    return true
  }

  // ---------- 내부 ----------

  connect(index) {
    this.client?.end(true)
    this.index = index
    this.connected = false
    this.lostAt = Date.now()
    this.on.conn('connecting', index)

    const url = wsUrl(this.brokers[index])
    if (!url) {
      // 주소가 잘못됐으면 접속하지 않는다. 주 브로커였다면 3초 뒤 예비로 넘어간다
      this.client = null
      return
    }
    let everConnected = false
    const client = mqtt.connect(url, {
      protocolVersion: 5, // 명령이 권한 때문에 막히면 브로커가 알려 준다
      clientId: `homekeeper-${this.user}-${Math.random().toString(16).slice(2, 8)}`,
      username: this.user,
      password: this.password,
      clean: true,
      keepalive: 5,
      reconnectPeriod: 1000,
      connectTimeout: 3000,
      queueQoSZero: false,
      will: this.sendsHeartbeat
        ? { topic: statusTopic(this.user), payload: JSON.stringify({ alive: 0 }), qos: 1, retain: true }
        : undefined,
    })
    this.client = client
    const mine = () => this.client === client // 브로커를 바꾼 뒤 옛 연결에서 온 이벤트는 무시

    client.on('connect', () => {
      if (!mine()) return
      this.connected = true
      everConnected = true
      client.subscribe(SUBSCRIBE, { qos: 1 })
      if (this.sendsHeartbeat) this.publish(statusTopic(this.user), { alive: 1 })
      this.on.conn('online', index)
    })

    client.on('close', () => {
      if (!mine()) return
      if (this.connected) this.lostAt = Date.now()
      this.connected = false
      // 한 번이라도 붙었던 브로커면 '끊김', 아직 못 붙었으면 '연결 중'
      if (!this.stopped) this.on.conn(everConnected ? 'offline' : 'connecting', index)
    })

    client.on('error', (err) => {
      if (!mine()) return
      if (AUTH_FAIL_CODES.includes(err.code)) {
        // 비밀번호 문제는 다시 시도해도 같으니 멈추고 알린다 (예비로 넘어가지도 않음)
        this.stop()
        this.on.conn('authfail', index)
      }
    })

    client.on('message', (topic, payload, packet) => {
      if (!mine()) return
      // 규약: 메시지는 JSON. 빈 메시지는 {} 로, JSON 이 아니면 무시 (공통 모듈과 같음)
      let data
      try {
        const text = decoder.decode(payload).trim()
        data = text ? JSON.parse(text) : {}
      } catch {
        return
      }
      if (data === null || typeof data !== 'object') return
      this.on.message(topic, data, packet.retain)
    })
  }

  watch() {
    if (this.stopped || this.connected || this.index !== 0 || this.brokers.length < 2) return
    if (Date.now() - this.lostAt >= FAILOVER_SEC * 1000) this.connect(1)
  }
}
