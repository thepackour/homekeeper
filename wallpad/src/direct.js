// 출입 허락 전용 '현관 직통' 연결 (팀 결정 2026-11-06: 허락은 허브를 거치지 않고 현관으로 바로 간다).
//
// 평소 연결(link.js)은 허브 브로커에 붙어 있다가, 허브가 꺼지면 3초 넘게 지나서야 예비(현관)로 넘어간다.
// 그 사이에 누른 허락이 사라지지 않도록, 현관 Pi 의 브로커(예비 = door.local)에 처음부터 붙어 있는
// 두 번째 연결을 하나 더 둔다. 허락은 두 연결로 동시에 보내고, 현관은 같은 id 를 한 번만 처리한다.
// 이 연결은 살아 있음/LWT 를 보내지 않는다(그건 평소 연결 몫). 문 열림 확인용으로 home/door/open 만 받는다.
import mqtt from 'mqtt'
import { TOPICS } from './config'
import { nowSec, wsUrl } from './link'

const decoder = new TextDecoder()

export class DirectLink {
  constructor({ user, password, broker, onOpen, onConn }) {
    this.url = wsUrl(broker)
    this.connected = false
    if (!this.url) return
    this.client = mqtt.connect(this.url, {
      protocolVersion: 5,
      clientId: `homekeeper-${user}-direct-${Math.random().toString(16).slice(2, 8)}`,
      username: user,
      password,
      clean: true,
      keepalive: 5,
      reconnectPeriod: 1000,
      connectTimeout: 3000,
    })
    this.client.on('connect', () => {
      this.connected = true
      onConn(true)
      this.client.subscribe(TOPICS.doorOpen, { qos: 1 })
    })
    this.client.on('close', () => {
      if (this.connected) onConn(false)
      this.connected = false
    })
    this.client.on('message', (topic, payload) => {
      try {
        onOpen(JSON.parse(decoder.decode(payload) || '{}'))
      } catch {
        // JSON 아니면 무시
      }
    })
  }

  // 허락 보내기. 붙어 있지 않으면 false
  publish(body) {
    if (!this.connected) return false
    this.client.publish(TOPICS.cmdApprove, JSON.stringify({ ...body, t: body.t ?? nowSec() }), { qos: 1 })
    return true
  }

  stop() {
    this.client?.end(true)
  }
}
