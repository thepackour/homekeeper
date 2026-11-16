// 가짜 메시지 보내기: 허브, 현관, 거실이 보낼 메시지를 흉내 내서 화면을 테스트한다.
// 토픽과 모양은 docs/mqtt.md 규약 그대로이고, "t"(초)는 자동으로 붙는다.
// PowerShell 따옴표 문제 없이 쓰려고 만든 도구라 실제 노드 코드와는 관계없다.
//
//   node tools/fake.mjs level 2                 의심 단계 (0~3)
//   node tools/fake.mjs mode away               모드 (home, away, sleep)
//   node tools/fake.mjs people 3                집 안 인원
//   node tools/fake.mjs judge door              판단 담당 (hub, door)
//   node tools/fake.mjs alert 3 tailgate        경보 (단계, 종류)
//   node tools/fake.mjs open auth               문 열림
//   node tools/fake.mjs loiter start            서성임 (start, over30, end)
//   node tools/fake.mjs visitor 사진.jpg        방문자 사진
//   node tools/fake.mjs alive door living hub   노드 살아 있음 (1초마다, Ctrl+C로 끊으면 LWT)
//   node tools/fake.mjs watch                   화면이 보내는 명령, 월패드 살아 있음 보기
//
// 옵션: --broker mqtt://localhost:1883  --user hub --pass 비밀번호
import { readFileSync } from 'node:fs'
import mqtt from 'mqtt'

const args = process.argv.slice(2)
function option(name, fallback) {
  const i = args.indexOf(`--${name}`)
  if (i < 0) return fallback
  return args.splice(i, 2)[1]
}
const broker = option('broker', 'mqtt://localhost:1883')
const user = option('user')
const pass = option('pass')
const [cmd, ...vals] = args

const t = () => Date.now() / 1000
const connect = (extra = {}) => mqtt.connect(broker, { username: user, password: pass, ...extra })

// 상태(home/state/)는 retain, 나머지는 retain 아님. 모두 QoS 1 (규약)
const MESSAGES = {
  level: ([lv]) => ['home/state/suspicion', { level: Number(lv) }, true],
  mode: ([mode]) => ['home/state/mode', { mode }, true],
  people: ([n]) => ['home/state/occupancy', { n: Number(n) }, true],
  judge: ([node]) => ['home/state/judge', { node }, true],
  alert: ([lv, type = 'tailgate']) => ['home/alert', { level: Number(lv), type }, false],
  open: ([by = 'auth']) => ['home/door/open', { state: 'open', by }, false],
  loiter: ([state]) => ['home/door/loiter', { state }, false],
  visitor: ([file]) => ['home/door/visitor', { img: readFileSync(file).toString('base64') }, false],
}

function fail(text) {
  console.error(text)
  process.exit(1)
}

if (MESSAGES[cmd]) {
  if (vals.length === 0 && !['alert', 'open'].includes(cmd)) fail(`값이 필요해요. 예: node tools/fake.mjs ${cmd} ...`)
  const [topic, body, retain] = MESSAGES[cmd](vals)
  const client = connect()
  client.on('error', (err) => fail(`접속 실패: ${err.message}`))
  client.on('connect', () => {
    client.publish(topic, JSON.stringify({ ...body, t: t() }), { qos: 1, retain }, (err) => {
      if (err) fail(`보내기 실패: ${err.message}`)
      const shown = cmd === 'visitor' ? `{"img":"(base64 ${body.img.length}자)"}` : JSON.stringify(body)
      console.log(`보냄 ${topic} ${shown}${retain ? ' (retain)' : ''}`)
      client.end()
    })
  })
} else if (cmd === 'alive') {
  // 노드마다 따로 접속해서 1초마다 {"alive":1}. 프로그램이 끝나면 브로커가 LWT {"alive":0}을 대신 보낸다
  if (vals.length === 0) fail('노드 이름이 필요해요. 예: node tools/fake.mjs alive door living hub')
  for (const node of vals) {
    const topic = `home/status/${node}`
    const client = connect({
      keepalive: 5,
      will: { topic, payload: JSON.stringify({ alive: 0 }), qos: 1, retain: true },
    })
    client.on('error', (err) => console.error(`${node} 접속 실패: ${err.message}`))
    client.on('connect', () => console.log(`${node}: 1초마다 살아 있음 보내는 중 (Ctrl+C로 끊기)`))
    setInterval(() => {
      if (client.connected) client.publish(topic, JSON.stringify({ alive: 1, t: t() }), { qos: 0, retain: true })
    }, 1000)
  }
} else if (cmd === 'watch') {
  const client = connect()
  client.on('error', (err) => fail(`접속 실패: ${err.message}`))
  client.on('connect', () => {
    client.subscribe(['home/cmd/#', 'home/status/wallpad'], { qos: 1 })
    console.log('명령과 월패드 살아 있음을 기다리는 중 (Ctrl+C로 끝)')
  })
  let lastBeat = ''
  client.on('message', (topic, payload, packet) => {
    const line = `${topic} qos=${packet.qos} retain=${packet.retain ? 1 : 0} ${payload}`
    if (topic.startsWith('home/status/')) {
      // 1초마다 오니까 alive 값이 바뀔 때만 보여 준다
      const alive = payload.toString().includes('"alive":1') ? 'alive1' : 'alive0'
      if (alive === lastBeat) return
      lastBeat = alive
    }
    console.log(`${new Date().toLocaleTimeString('ko-KR', { hour12: false })} ${line}`)
  })
} else {
  console.log(readFileSync(new URL(import.meta.url), 'utf8').split('\n').slice(0, 16).join('\n'))
}
