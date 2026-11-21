import { useEffect, useReducer, useRef } from 'react'
import { Link } from './link'
import { DirectLink } from './direct'
import {
  ALERT_TYPES,
  APPROVE_ACK_SEC,
  CMD_TIMEOUT_SEC,
  DISMISS_FROM,
  VISITOR_REQ_SEC,
  AUTH_METHOD,
  DOOR_BY,
  LEVELS,
  MODES,
  NODES,
  STALE_SEC,
  TOPICS,
  label,
} from './config'

// 시각은 메시지의 "t" 대신 이 화면이 받은 시각을 쓴다.
// (핫스팟에 인터넷이 없으면 Pi 시계가 틀릴 수 있어서)

const initialState = {
  conn: 'connecting', // connecting | online | offline | authfail
  brokerIndex: 0, // 0 = 주, 1 = 예비
  connectedAt: null,
  mode: null, // {value, at}
  occupancy: null, // {n, at}
  level: null, // 0~3, home/state/suspicion 값만 따른다
  judge: null, // 'hub' | 'door' ...
  door: { open: null, loiter: null, visitor: null, auth: null }, // auth: 마지막 인증 {ok, method, face, score, at}
  nodes: {}, // {door: {alive, seen}}
  nodeState: {}, // {door: 'ok' | 'lost' | 'checking'}
  // 보낸 명령이 실제로 반영됐는지 기다리는 중인 것. 화면은 명령이 아니라 확정된 상태만 믿는다
  pending: { mode: null, dismiss: null }, // mode: {value, until}, dismiss: {until}
  approval: null, // {id, until, via, result: null | 'ok' | 'timeout'}
  direct: false, // 현관 직통 연결(허락 전용)이 붙어 있는가. 허브 브로커가 끊겨도 허락은 이걸로 보낼 수 있다
  log: [],
}

function addLog(state, at, kind, text) {
  return { ...state, log: [{ at, kind, text }, ...state.log].slice(0, 40) }
}

// 노드 하나의 상태: ok(살아 있음) / lost(응답 없음) / checking(확인 중)
function nodeStateOf(node, now, connectedAt) {
  if (node?.alive === 0) return 'lost'
  const since = Math.max(node?.seen ?? 0, connectedAt)
  if (now - since > STALE_SEC * 1000) return 'lost'
  return node?.seen >= connectedAt ? 'ok' : 'checking'
}

// 보낸 명령의 마감 시간이 지났는지 본다 (연결이 끊겨 있어도 판단)
function expire(state, now) {
  let next = state
  const at = new Date(now)
  const { mode, dismiss } = state.pending
  if (mode && now > mode.until) {
    next = addLog({ ...next, pending: { ...next.pending, mode: null } }, at, 'alarm',
      `허브 응답 없음: ${label(MODES, mode.value)}(으)로 안 바뀜`)
  }
  if (dismiss && now > dismiss.until) {
    next = addLog({ ...next, pending: { ...next.pending, dismiss: null } }, at, 'alarm', '허브 응답 없음: 경보가 해제되지 않음')
  }
  const ap = state.approval
  if (ap && !ap.result && now > ap.until) {
    next = addLog({ ...next, approval: { ...ap, result: 'timeout' } }, at, 'alarm', '현관 응답 없음: 허락 후 문이 열리지 않음')
  }
  return next
}

// 현관이 허락을 받고 문을 열었는지 (home/door/open {"by":"approve","id":...})
function confirmApproval(state, data, at) {
  const ap = state.approval
  if (!ap || ap.result || data.by !== 'approve') return state
  if (data.id != null && data.id !== ap.id) return state // 현관이 id 를 돌려주면 대조까지
  return addLog({ ...state, approval: { ...ap, result: 'ok' } }, at, 'info', '허락으로 문 열림 확인')
}

function tick(state, now) {
  state = expire(state, now)
  if (state.conn !== 'online') return state // 내가 끊긴 동안에는 노드 상태를 판단하지 않는다
  let next = state
  const nodeState = {}
  for (const { key, label: name } of NODES) {
    const before = state.nodeState[key]
    const after = nodeStateOf(state.nodes[key], now, state.connectedAt)
    nodeState[key] = after
    if (after === 'lost' && before !== 'lost') next = addLog(next, new Date(now), 'warn', `${name} 응답 없음`)
    if (after === 'ok' && before === 'lost') next = addLog(next, new Date(now), 'info', `${name} 다시 연결됨`)
  }
  const same = NODES.every(({ key }) => nodeState[key] === state.nodeState[key])
  return same && next === state ? state : { ...next, nodeState }
}

function onMessage(state, { topic, data, retained, at }) {
  const live = !retained // retain 으로 받은 옛 값은 기록에 남기지 않는다

  if (topic.startsWith('home/status/')) {
    const key = topic.split('/')[2]
    if (!NODES.some((n) => n.key === key) || !('alive' in data)) return state
    const alive = Number(data.alive) === 1 ? 1 : 0
    return { ...state, nodes: { ...state.nodes, [key]: { alive, seen: at.getTime() } } }
  }

  switch (topic) {
    case TOPICS.mode: {
      const value = String(data.mode ?? '')
      if (!value) return state
      let next = { ...state, mode: { value, at } }
      if (state.pending.mode?.value === value) {
        next = addLog({ ...next, pending: { ...next.pending, mode: null } }, at, 'info',
          `허브가 확정: ${label(MODES, value)}`)
      }
      const changed = state.mode && state.mode.value !== value
      return changed && live ? addLog(next, at, 'info', `모드 바뀜: ${label(MODES, value)}`) : next
    }
    case TOPICS.occupancy: {
      const n = Number(data.n)
      return Number.isFinite(n) ? { ...state, occupancy: { n, at } } : state
    }
    case TOPICS.suspicion: {
      const level = Number(data.level)
      if (![0, 1, 2, 3].includes(level)) return state
      let next = { ...state, level }
      if (state.pending.dismiss && level < DISMISS_FROM) {
        next = addLog({ ...next, pending: { ...next.pending, dismiss: null } }, at, 'info', '허브가 경보 해제를 확정')
      }
      if (!live || state.level === level) return next
      if (level === 0) return state.level == null ? next : addLog(next, at, 'info', '의심 단계 0: 정상으로 돌아옴')
      return addLog(next, at, level === 3 ? 'alarm' : 'warn', `의심 단계 ${level}: ${LEVELS[level].title}`)
    }
    case TOPICS.judge: {
      const node = String(data.node ?? '')
      if (!node) return state
      const next = { ...state, judge: node }
      return live && state.judge && state.judge !== node
        ? addLog(next, at, 'warn', `판단 담당 바뀜: ${label(NODES, node)}`)
        : next
    }
    case TOPICS.alert: {
      const type = data.type ? (ALERT_TYPES[data.type] ?? data.type) : '경보'
      const lv = Number.isFinite(Number(data.level)) ? ` (단계 ${data.level})` : ''
      return addLog(state, at, 'alarm', `경보: ${type}${lv}`)
    }
    case TOPICS.doorOpen: {
      const by = data.by ? (DOOR_BY[data.by] ?? data.by) : null
      const next = { ...state, door: { ...state.door, open: { at, by } } }
      return confirmApproval(addLog(next, at, 'info', by ? `현관 문 열림 (${by})` : '현관 문 열림'), data, at)
    }
    case TOPICS.doorLoiter: {
      const s = String(data.state ?? '')
      if (!s) return state
      const next = { ...state, door: { ...state.door, loiter: { state: s, at } } }
      if (s === 'start') return addLog(next, at, 'warn', '문 앞 서성임 시작')
      if (s === 'over30') return addLog(next, at, 'warn', '문 앞 30초 넘게 서성임')
      if (s === 'end') return addLog(next, at, 'info', '문 앞 서성임 끝')
      return next
    }
    case TOPICS.doorAuth: {
      // 등록 안 된 카드는 face, score 없이 {"result":"fail","method":"card"} 로 온다
      const ok = data.result === 'ok'
      const score = typeof data.score === 'number' ? data.score : null
      const auth = { ok, method: data.method ?? null, face: data.face ?? null, score, at }
      const next = { ...state, door: { ...state.door, auth } }
      const how = AUTH_METHOD[auth.method] ?? auth.method ?? ''
      const text =
        score == null
          ? ok
            ? `출입 인증 성공 (${how})`
            : '등록 안 된 카드'
          : `출입 인증 ${ok ? '성공' : '실패'} · 위험 ${score}점 · ${how}`
      return addLog(next, at, ok ? 'info' : 'warn', text)
    }
    case TOPICS.doorPwfail: {
      const n = Number(data.count)
      return addLog(state, at, 'warn', Number.isFinite(n) ? `현관 비밀번호 틀림 (${n}번째)` : '현관 비밀번호 틀림')
    }
    case TOPICS.doorVisitor: {
      const src = imageSrc(data.img)
      if (!src) return state
      // req: 허락에 붙여 보낼 '어떤 방문 요청에 대한 답인지' (보낸 쪽 시각 "t" 그대로)
      const next = { ...state, door: { ...state.door, visitor: { src, at, req: data.t ?? null } } }
      return addLog(next, at, 'info', '방문자 사진 받음')
    }
    default:
      return state
  }
}

// base64 글자를 <img>에 넣을 수 있는 주소로. 앞부분을 보고 JPEG/PNG를 구분한다.
function imageSrc(img) {
  if (typeof img !== 'string' || img.length < 16) return null
  if (img.startsWith('data:image/')) return img
  const type = img.startsWith('iVBOR') ? 'png' : 'jpeg'
  return `data:image/${type};base64,${img}`
}

function reducer(state, action) {
  switch (action.type) {
    case 'conn': {
      const { conn, index } = action
      const next = { ...state, conn, brokerIndex: index }
      if (conn === 'online') {
        next.connectedAt = action.now
        const where = index === 0 ? '주 브로커' : '예비 브로커'
        if (state.conn !== 'online') return addLog(next, new Date(action.now), 'info', `${where}에 연결됨`)
      }
      if (conn === 'offline' && state.conn === 'online') return addLog(next, new Date(action.now), 'warn', '브로커 연결 끊김')
      return next
    }
    case 'message':
      return onMessage(state, action)
    case 'tick':
      return tick(state, action.now)
    case 'pend':
      return { ...state, pending: { ...state.pending, ...action.pending } }
    case 'approval':
      return addLog({ ...state, approval: action.approval }, new Date(), 'sent', action.text)
    case 'direct':
      return { ...state, direct: action.on }
    case 'directOpen': // 현관 직통 연결로 받은 문 열림: 허락 확인에만 쓴다(기록 중복 방지)
      return confirmApproval(state, action.data, new Date())
    case 'log':
      return addLog(state, new Date(), action.kind, action.text)
    default:
      return state
  }
}

// 브로커에 붙어서 집 상태를 받고, 명령을 보내는 훅
export function useHome(login, brokers) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const linkRef = useRef(null)
  const directRef = useRef(null)
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state // 허락 보낼 때 마지막 방문자 정보를 읽으려고
  })
  const [primary, backup] = brokers

  useEffect(() => {
    const link = new Link({
      user: login.user,
      password: login.password,
      brokers: [primary, backup],
      on: {
        conn: (conn, index) => dispatch({ type: 'conn', conn, index, now: Date.now() }),
        message: (topic, data, retained) => dispatch({ type: 'message', topic, data, retained, at: new Date() }),
      },
    })
    linkRef.current = link
    link.start()
    const direct = backup
      ? new DirectLink({
          user: login.user,
          password: login.password,
          broker: backup,
          onOpen: (data) => dispatch({ type: 'directOpen', data }),
          onConn: (on) => dispatch({ type: 'direct', on }),
        })
      : null
    directRef.current = direct
    const timer = setInterval(() => dispatch({ type: 'tick', now: Date.now() }), 1000)

    // 개발 모드(StrictMode)에서 두 번 연결되지 않도록 정리
    return () => {
      clearInterval(timer)
      linkRef.current = null
      link.stop()
      directRef.current = null
      direct?.stop()
    }
  }, [login.user, login.password, primary, backup])

  // 명령 보내기 (QoS 1). 브로커가 권한 없다고 하면 기록에 남긴다
  function command(topic, data, text) {
    const sent = linkRef.current?.publish(topic, data, (err) => {
      if (err) dispatch({ type: 'log', kind: 'alarm', text: `${text} 실패: ${err.code === 135 ? '권한 없음' : err.message}` })
    })
    dispatch(sent ? { type: 'log', kind: 'sent', text } : { type: 'log', kind: 'alarm', text: `${text} 못 보냄: 연결 끊김` })
    return sent
  }

  const until = (sec) => Date.now() + sec * 1000

  // 출입 허락: 평소 연결과 현관 직통 연결 둘 다로 보낸다. 같은 id 라 현관은 한 번만 처리한다
  function approve() {
    const link = linkRef.current
    const direct = directRef.current
    const visitor = stateRef.current.door.visitor
    const fresh = visitor && Date.now() - visitor.at.getTime() < VISITOR_REQ_SEC * 1000
    const body = {
      ok: 1,
      id: Math.random().toString(16).slice(2, 10),
      ...(fresh && visitor.req != null && { req: visitor.req }),
    }
    const via = []
    if (link?.publish(TOPICS.cmdApprove, body)) via.push(link.index === 0 ? '허브 브로커' : '예비 브로커')
    // 평소 연결이 이미 현관 브로커(예비)에 붙어 있으면 같은 곳이라 한 번만
    if (!(link?.connected && link.index === 1) && direct?.publish(body)) via.push('현관 직통')
    if (via.length === 0) return dispatch({ type: 'log', kind: 'alarm', text: '출입 허락 못 보냄: 연결 끊김' })
    dispatch({
      type: 'approval',
      approval: { id: body.id, until: until(APPROVE_ACK_SEC), via, result: null },
      text: `출입 허락 보냄 (${via.join(', ')})`,
    })
  }

  return {
    ...state,
    setMode: (mode) => {
      if (command(TOPICS.cmdMode, { mode }, `모드 변경 요청: ${label(MODES, mode)}`))
        dispatch({ type: 'pend', pending: { mode: { value: mode, until: until(CMD_TIMEOUT_SEC) } } })
    },
    approve,
    dismiss: () => {
      if (command(TOPICS.cmdDismiss, {}, '경보 해제 보냄'))
        dispatch({ type: 'pend', pending: { dismiss: { until: until(CMD_TIMEOUT_SEC) } } })
    },
    switchBroker: (index) => linkRef.current?.switchBroker(index),
  }
}
