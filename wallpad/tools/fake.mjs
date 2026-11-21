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
//   node tools/fake.mjs auth ok 2 card+pw none  현관 인증 결과 (ok/fail, 위험 점수, 방법, 얼굴)
//   node tools/fake.mjs pwfail 1                현관 비밀번호 틀림 (몇 번째)
//   node tools/fake.mjs alive door living hub   노드 살아 있음 (1초마다, Ctrl+C로 끊으면 LWT)
//   node tools/fake.mjs watch                   화면이 보내는 명령, 월패드 살아 있음 보기
//   node tools/fake.mjs answer                  허브·현관처럼 명령에 답하기 (모드 확정, 경보 해제, 허락→문 열림)
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
  auth: ([result = 'ok', score, method = 'card', face]) => [
    'home/door/auth',
    { result, method, ...(face && { face }), ...(score != null && { score: Number(score) }) },
    false,
  ],
  pwfail: ([count]) => ['home/door/pwfail', { count: Number(count) }, false],
}

function fail(text) {
  console.error(text)
  process.exit(1)
}

if (MESSAGES[cmd]) {
  if (vals.length === 0 && !['alert', 'open', 'auth'].includes(cmd)) fail(`값이 필요해요. 예: node tools/fake.mjs ${cmd} ...`)
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
} else if (cmd === 'answer') {
  // 화면의 '확정 대기'를 시험: 허브는 모드·경보 해제를 상태로 확정, 현관은 허락에 문을 연다.
  // 현관은 허락이 두 길(허브 브로커, 현관 직통)로 와도 같은 id 는 한 번만 처리한다.
  // --broker 를 여러 번 줄 수 없으니 현관 직통 브로커는 --door mqtt://localhost:1884 로 따로 준다
  const door = option('door')
  const seen = new Set()
  const send = (c, topic, body, retain = false) => c.publish(topic, JSON.stringify({ ...body, t: t() }), { qos: 1, retain })
  const listen = (c, name) => {
    c.on('error', (err) => console.error(`${name} 접속 실패: ${err.message}`))
    c.on('connect', () => {
      c.subscribe('home/cmd/#', { qos: 1 })
      console.log(`${name}: 명령에 답하는 중`)
    })
    c.on('message', (topic, payload) => {
      const msg = JSON.parse(payload.toString() || '{}')
      if (topic === 'home/cmd/mode') send(c, 'home/state/mode', { mode: msg.mode }, true)
      else if (topic === 'home/cmd/dismiss') send(c, 'home/state/suspicion', { level: 0 }, true)
      else if (topic === 'home/cmd/approve') {
        if (seen.has(msg.id)) return console.log(`${name}: 허락 ${msg.id} 이미 처리함 (중복 무시)`)
        seen.add(msg.id)
        console.log(`${name}: 허락 ${msg.id} req=${msg.req ?? '-'} → 문 열기`)
        if (msg.ok) setTimeout(() => send(c, 'home/door/open', { state: 'open', by: 'approve', id: msg.id }), 500)
      } else return
      console.log(`${name}: ${topic} ${payload}`)
    })
  }
  listen(connect(), '허브')
  if (door) listen(mqtt.connect(door, { username: user, password: pass }), '현관 직통')
} else {
  console.log(readFileSync(new URL(import.meta.url), 'utf8').split('\n').slice(0, 19).join('\n'))
}
