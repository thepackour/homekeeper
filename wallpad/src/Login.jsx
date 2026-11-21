import { useState } from 'react'
import { ACCOUNTS, DEFAULT_BROKERS, WS_PORT, label } from './config'
import { wsUrl } from './link'
import { isDefaultPin } from './pin'

// 주, 예비 브로커 주소 입력 칸 (로그인 화면과 설정에서 같이 씀)
function BrokerFields({ value, onChange }) {
  const [primary, backup] = value
  return (
    <fieldset className="field-group">
      <legend>브로커 주소</legend>
      <label className="field">
        <span>주 (허브)</span>
        <input value={primary} onChange={(e) => onChange([e.target.value, backup])} spellCheck="false" />
      </label>
      <label className="field">
        <span>예비 (현관)</span>
        <input value={backup} onChange={(e) => onChange([primary, e.target.value])} spellCheck="false" />
      </label>
      <p className="hint">이름만 쓰면 WebSocket {WS_PORT} 포트로 붙어요. 다른 포트는 이름:포트로 써요.</p>
      {!DEFAULT_BROKERS[0] && (
        <p className="hint">common/config.json을 찾지 못해서 기본 주소가 없어요. 직접 넣어 주세요.</p>
      )}
    </fieldset>
  )
}

function checkBrokers([primary, backup]) {
  if (!wsUrl(primary)) return '주 브로커 주소를 확인해 주세요.'
  if (backup.trim() && !wsUrl(backup)) return '예비 브로커 주소를 확인해 주세요.'
  return null
}

const tidy = (brokers) => brokers.map((b) => b.trim())

// 처음 켤 때: 계정, 비밀번호, 브로커 주소를 받는다. 이 기기에만 저장된다.
export function Login({ brokers, failed, onSubmit }) {
  const [user, setUser] = useState(failed?.user ?? 'wallpad')
  const [password, setPassword] = useState('')
  const [addr, setAddr] = useState(brokers)
  const [error, setError] = useState(null)

  const submit = (e) => {
    e.preventDefault()
    const problem = checkBrokers(addr)
    if (problem) return setError(problem)
    onSubmit({ user, password }, tidy(addr))
  }

  return (
    <div className="login">
      <form className="login-card" onSubmit={submit}>
        <h1>홈키파</h1>
        <p className="login-lead">이 기기에서 쓸 계정으로 로그인하세요. 이 기기에만 저장돼요.</p>

        {failed && (
          <p className="login-error" role="alert">
            로그인 실패: {label(ACCOUNTS, failed.user)}({failed.user}) 계정의 비밀번호가 맞지 않거나, {failed.broker}에
            없는 계정이에요.
          </p>
        )}

        <div className="field">
          <span>계정</span>
          <div className="seg" role="group" aria-label="계정">
            {ACCOUNTS.map((a) => (
              <button type="button" key={a.key} aria-pressed={user === a.key} onClick={() => setUser(a.key)}>
                {a.label} <small>{a.key}</small>
              </button>
            ))}
          </div>
        </div>

        <label className="field">
          <span>비밀번호</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        <BrokerFields value={addr} onChange={setAddr} />

        {error && <p className="login-error">{error}</p>}
        <button className="btn-primary" type="submit">
          접속
        </button>
      </form>
    </div>
  )
}

// 화면 오른쪽 위 '설정': 계정, 연결된 브로커, 주소 바꾸기
export function Settings({ login, brokers, brokerIndex, online, onBackToPrimary, onBrokers, onLogout, onChangePin, onClose }) {
  const [addr, setAddr] = useState(brokers)
  const [error, setError] = useState(null)
  const changed = addr.some((a, i) => a.trim() !== brokers[i])

  const save = (e) => {
    e.preventDefault()
    const problem = checkBrokers(addr)
    if (problem) return setError(problem)
    onBrokers(tidy(addr))
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <form className="sheet" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <div className="sheet-head">
          <h2>설정</h2>
          <button type="button" className="btn-text" onClick={onClose}>
            닫기
          </button>
        </div>

        <div className="sheet-row">
          <div>
            <p className="card-label">계정</p>
            <p>
              {label(ACCOUNTS, login.user)} ({login.user})
            </p>
          </div>
          <button type="button" className="btn-line" onClick={onLogout}>
            로그아웃
          </button>
        </div>

        <div className="sheet-row">
          <div>
            <p className="card-label">지금 연결</p>
            <p>
              {brokerIndex === 1 ? '예비' : '주'} 브로커 {brokers[brokerIndex]} · {online ? '연결됨' : '연결 안 됨'}
            </p>
            {brokerIndex === 1 && (
              <p className="hint">허브가 끊겨서 예비로 넘어왔어요. 허브가 돌아와도 자동으로 돌아가지 않아요.</p>
            )}
          </div>
          {brokerIndex === 1 && (
            <button type="button" className="btn-line" onClick={onBackToPrimary}>
              주 브로커로 돌아가기
            </button>
          )}
        </div>

        <div className="sheet-row">
          <div>
            <p className="card-label">PIN</p>
            <p className="hint">경보 해제, 재택으로 바꿀 때 물어요{isDefaultPin() ? ' · 지금 기본 1234' : ''}</p>
          </div>
          <button type="button" className="btn-line" onClick={onChangePin}>
            PIN 바꾸기
          </button>
        </div>

        <BrokerFields value={addr} onChange={setAddr} />
        {error && <p className="login-error">{error}</p>}
        <button className="btn-primary" type="submit" disabled={!changed}>
          주소 저장하고 다시 연결
        </button>
      </form>
    </div>
  )
}
