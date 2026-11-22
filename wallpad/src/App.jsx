import { useEffect, useState } from 'react'
import { useHome } from './useHome'
import { Login, Settings } from './Login'
import { PinChange, PinPad } from './PinPad'
import { loadBrokers, loadLogin, saveBrokers, saveLogin } from './saved'
import { AUTH_METHOD, DISMISS_FROM, FACE, LEVELS, LOITER, MODES, NODES, RISK_RULE, label, riskStep } from './config'

const fmtTime = (d) =>
  d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
const fmtTimeSec = (d) =>
  d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
const fmtDate = (d) => d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' })

function useNow(ms) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

const CONN_TEXT = { connecting: '연결 중', online: '연결됨', offline: '연결 끊김' }

// 처음 켤 때는 로그인 화면, 로그인 정보가 있으면 집 상태 화면
export default function App() {
  const [login, setLogin] = useState(loadLogin)
  const [brokers, setBrokers] = useState(loadBrokers)
  const [failed, setFailed] = useState(null) // 로그인 실패 정보 {user, broker}

  if (!login) {
    return (
      <Login
        brokers={brokers}
        failed={failed}
        onSubmit={(nextLogin, nextBrokers) => {
          saveLogin(nextLogin)
          saveBrokers(nextBrokers)
          setBrokers(nextBrokers)
          setFailed(null)
          setLogin(nextLogin)
        }}
      />
    )
  }

  return (
    <Home
      // 계정이나 주소가 바뀌면 화면을 새로 만들어 이전 브로커의 값이 남지 않게 한다
      key={`${login.user}|${brokers.join('|')}`}
      login={login}
      brokers={brokers}
      onAuthFail={(index) => {
        saveLogin(null) // 틀린 비밀번호로 계속 다시 붙지 않도록 지운다
        setFailed({ user: login.user, broker: brokers[index] })
        setLogin(null)
      }}
      onLogout={() => {
        saveLogin(null)
        setFailed(null)
        setLogin(null)
      }}
      onBrokers={(next) => {
        saveBrokers(next)
        setBrokers(next)
      }}
    />
  )
}

function Home({ login, brokers, onAuthFail, onLogout, onBrokers }) {
  const home = useHome(login, brokers)
  const now = useNow(10_000)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [pinAsk, setPinAsk] = useState(null) // {title, then} PIN 맞으면 then()
  const [pinChange, setPinChange] = useState(false)
  const online = home.conn === 'online'
  const broker = brokers[home.brokerIndex]

  useEffect(() => {
    if (home.conn === 'authfail') onAuthFail(home.brokerIndex)
  }, [home.conn, home.brokerIndex, onAuthFail])

  const approve = () => {
    if (window.confirm('현관 출입을 허락할까요?')) home.approve()
  }
  // 경보 해제와 경계 풀기(외출·취침 → 재택)는 PIN 을 묻는다
  const dismiss = () => setPinAsk({ title: '경보 해제 PIN', then: home.dismiss })
  const setMode = (mode) => {
    if (mode === 'home' && ['away', 'sleep'].includes(home.mode?.value)) {
      setPinAsk({ title: '재택으로 바꾸기 PIN', then: () => home.setMode(mode) })
    } else home.setMode(mode)
  }
  const pendingMode = home.pending.mode?.value

  return (
    <div className={`app ${online ? '' : 'is-offline'}`}>
      <header className="topbar">
        <h1>홈키파</h1>
        <div className="topbar-right">
          <span className={`conn conn-${home.conn}`}>
            <span className="conn-dot" aria-hidden="true" />
            {CONN_TEXT[home.conn] ?? home.conn}
            <small className={home.brokerIndex === 1 ? 'conn-backup' : ''}>
              {home.brokerIndex === 1 ? '예비' : '주'} {broker}
            </small>
          </span>
          <span className="date">{fmtDate(now)}</span>
          <strong className="clock">{fmtTime(now)}</strong>
          <button className="btn-text" onClick={() => setSettingsOpen(true)}>
            설정
          </button>
        </div>
      </header>

      <StatusBand home={home} online={online} onDismiss={dismiss} />
      <NodeRow home={home} online={online} />

      <div className="cards">
        <section className="card card-mode">
          <h2 className="card-label">보안 모드</h2>
          <p className="card-value">{home.mode ? label(MODES, home.mode.value) : '—'}</p>
          <p className="card-sub">
            {pendingMode
              ? `${label(MODES, pendingMode)}(으)로 바꾸는 중… 허브 확정 대기`
              : home.mode
                ? `${fmtTime(home.mode.at)} 받음`
                : '받은 값 없음'}
          </p>
          <div className="seg" role="group" aria-label="모드 변경">
            {MODES.map((m) => (
              <button
                key={m.key}
                aria-pressed={home.mode?.value === m.key}
                className={pendingMode === m.key ? 'is-pending' : ''}
                disabled={!online || !!pendingMode || home.mode?.value === m.key}
                onClick={() => setMode(m.key)}
              >
                {m.label}
                {pendingMode === m.key && '…'}
              </button>
            ))}
          </div>
        </section>

        <section className="card card-people">
          <h2 className="card-label">집 안 인원</h2>
          <p className="card-value">
            {home.occupancy ? home.occupancy.n : '—'}
            {home.occupancy && <span className="unit">명</span>}
          </p>
          <p className="card-sub">{home.occupancy ? `${fmtTime(home.occupancy.at)} 받음` : '받은 값 없음'}</p>
        </section>

        <DoorCard door={home.door} approval={home.approval} canApprove={online || home.direct} onApprove={approve} />
      </div>

      <section className="log">
        <h2 className="card-label">기록</h2>
        {home.log.length === 0 ? (
          <p className="log-empty">이 화면을 연 뒤로 생긴 기록이 없어요.</p>
        ) : (
          <ol>
            {home.log.map((e, i) => (
              <li key={`${e.at.getTime()}-${i}`} className={`log-${e.kind}`}>
                <time>{fmtTimeSec(e.at)}</time>
                <span>{e.text}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      {settingsOpen && (
        <Settings
          login={login}
          brokers={brokers}
          brokerIndex={home.brokerIndex}
          online={online}
          onBackToPrimary={() => home.switchBroker(0)}
          onBrokers={(next) => {
            setSettingsOpen(false)
            onBrokers(next)
          }}
          onLogout={onLogout}
          onChangePin={() => {
            setSettingsOpen(false)
            setPinChange(true)
          }}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {pinAsk && (
        <PinPad
          title={pinAsk.title}
          onOk={() => {
            setPinAsk(null)
            pinAsk.then()
          }}
          onCancel={() => setPinAsk(null)}
        />
      )}
      {pinChange && <PinChange onDone={() => setPinChange(false)} />}
    </div>
  )
}

// 맨 위 띠: 의심 단계(home/state/suspicion) 값만 따라간다. retain 값이라 새로고침해도 그대로.
function StatusBand({ home, online, onDismiss }) {
  const lv = home.level
  let cls, kicker, title, note
  if (!online) {
    cls = 'off'
    kicker = '의심 단계'
    title = CONN_TEXT[home.conn]
    note =
      lv == null
        ? '브로커에 연결되지 않았어요.'
        : `마지막으로 받은 단계는 ${lv} (${LEVELS[lv].title})예요. 지금 상태는 알 수 없어요.`
  } else if (lv == null) {
    cls = 'wait'
    kicker = '의심 단계'
    title = '대기'
    note = '허브에서 의심 단계를 아직 받지 못했어요.'
  } else {
    cls = LEVELS[lv].cls
    kicker = `의심 단계 ${lv}`
    title = LEVELS[lv].title
    note = LEVELS[lv].note
  }
  const canDismiss = online && lv >= DISMISS_FROM

  return (
    <section className={`band band-${cls}`} role="status" aria-live="polite">
      <div>
        <p className="band-kicker">{kicker}</p>
        <p className="band-title">{title}</p>
        <p className="band-note">{note}</p>
      </div>
      {canDismiss && (
        <button className="btn-dismiss" onClick={onDismiss}>
          경보 해제
        </button>
      )}
    </section>
  )
}

// 노드 살아 있음(home/status/<노드>)과 판단 담당(home/state/judge)
function NodeRow({ home, online }) {
  const judge = home.judge
  return (
    <section className="nodes" aria-label="기기 상태">
      {NODES.map((n) => {
        const s = online ? (home.nodeState[n.key] ?? 'checking') : 'unknown'
        const text = s === 'lost' ? `${n.label} 응답 없음` : s === 'checking' ? `${n.label} 확인 중` : n.label
        return (
          <span key={n.key} className={`node node-${s}`}>
            <span className="node-dot" aria-hidden="true" />
            {text}
          </span>
        )
      })}
      <span className={`judge ${judge && judge !== 'hub' ? 'judge-backup' : ''}`}>
        판단: {judge ? label(NODES, judge) : '—'}
        {judge && judge !== 'hub' && ' (허브 대신)'}
      </span>
    </section>
  )
}

// 현관이 마지막 인증 때 매긴 위험 점수 (home/door/auth). "지금" 점수는 허브의 home/state/risk 몫
function RiskLine({ auth }) {
  if (!auth) return <p className="risk risk-none">위험 점수: 아직 인증 없음</p>
  if (auth.score == null) {
    return (
      <p className="risk risk-none">
        마지막 인증 {fmtTime(auth.at)} · {auth.ok ? '성공' : '등록 안 된 카드'}
      </p>
    )
  }
  const step = riskStep(auth.score)
  const details = [
    AUTH_METHOD[auth.method] ?? auth.method,
    auth.ok ? '성공' : '실패',
    auth.face && (FACE[auth.face] ?? auth.face),
    fmtTime(auth.at),
  ].filter(Boolean)
  return (
    <div className={`risk risk-${step.cls}`}>
      <p className="risk-head">
        <strong>위험 {auth.score}점</strong> {step.title}
      </p>
      <p className="risk-detail">마지막 인증 · {details.join(' · ')}</p>
      <p className="risk-rule">{RISK_RULE}</p>
    </div>
  )
}

// 허락을 보낸 뒤: 어느 길로 갔는지, 현관이 실제로 문을 열었는지
const APPROVAL_TEXT = {
  null: (a) => `허락 보냄 (${a.via.join(', ')}) · 문 열림 확인 기다리는 중`,
  ok: () => '허락으로 문 열림 확인',
  timeout: () => '현관 응답 없음 · 문이 열렸는지 확인하세요',
}

function DoorCard({ door, approval, canApprove, onApprove }) {
  const { open, loiter, visitor } = door
  return (
    <section className="card card-door">
      <h2 className="card-label">현관</h2>
      {visitor && (
        <figure className="visitor">
          <img src={visitor.src} alt="방문자 사진" />
          <figcaption>방문자 사진 · {fmtTimeSec(visitor.at)}</figcaption>
        </figure>
      )}
      <p className={`loiter loiter-${loiter?.state ?? 'none'}`}>
        {loiter ? (LOITER[loiter.state] ?? loiter.state) : '문 앞 소식 없음'}
      </p>
      <p className="card-sub">
        {open ? `마지막 문 열림 ${fmtTime(open.at)}${open.by ? ` (${open.by})` : ''}` : '문 열림 기록 없음'}
      </p>
      <RiskLine auth={door.auth} />
      {approval && (
        <p className={`approval approval-${approval.result ?? 'wait'}`}>{APPROVAL_TEXT[approval.result](approval)}</p>
      )}
      <button className="btn-primary" disabled={!canApprove || (approval && !approval.result)} onClick={onApprove}>
        출입 허락
      </button>
    </section>
  )
}
