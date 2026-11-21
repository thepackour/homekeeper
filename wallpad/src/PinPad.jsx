import { useEffect, useState } from 'react'
import { PIN_LEN, checkPin, isDefaultPin, lockedFor, savePin } from './pin'

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '지움', '0', '취소']

// 숫자 키패드 (터치용 큰 버튼). PIN_LEN 자리가 차면 onDone(입력값)
function Keypad({ title, hint, error, onDone, onCancel }) {
  const [digits, setDigits] = useState('')
  const [, setTick] = useState(0)
  const lock = lockedFor()

  useEffect(() => {
    if (!lock) return
    const id = setInterval(() => setTick((n) => n + 1), 1000) // 잠금 남은 초 다시 그리기
    return () => clearInterval(id)
  }, [lock])

  const press = (k) => {
    if (k === '취소') return onCancel()
    if (lockedFor()) return
    if (k === '지움') return setDigits((d) => d.slice(0, -1))
    const next = digits + k
    if (next.length < PIN_LEN) return setDigits(next)
    setDigits('')
    onDone(next)
  }

  return (
    <div className="sheet-backdrop">
      <div className="sheet pinpad" role="dialog" aria-label={title}>
        <h2>{title}</h2>
        <p className="pin-dots" aria-label={`${digits.length}자리 입력됨`}>
          {Array.from({ length: PIN_LEN }, (_, i) => (i < digits.length ? '●' : '○')).join(' ')}
        </p>
        <p className="pin-msg">{lock ? `${lock}초 동안 입력할 수 없어요.` : (error ?? hint ?? '')}</p>
        <div className="pin-keys">
          {KEYS.map((k) => (
            <button key={k} type="button" className={/\d/.test(k) ? 'pin-num' : 'pin-fn'} onClick={() => press(k)}>
              {k}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// PIN 확인 후 onOk. 3번 틀리면 30초 잠김(pin.js)
export function PinPad({ title, onOk, onCancel }) {
  const [error, setError] = useState(null)
  const hint = isDefaultPin() ? '기본 PIN 1234 사용 중이에요. 설정에서 바꾸세요.' : null
  return (
    <Keypad
      title={title}
      hint={hint}
      error={error}
      onCancel={onCancel}
      onDone={(pin) => (checkPin(pin) ? onOk() : setError(lockedFor() ? null : 'PIN이 틀렸어요.'))}
    />
  )
}

// 설정 → PIN 바꾸기: 지금 PIN → 새 PIN → 한 번 더
export function PinChange({ onDone }) {
  const [step, setStep] = useState('old') // old | new | again
  const [first, setFirst] = useState(null)
  const [error, setError] = useState(null)
  const titles = { old: '지금 PIN', new: '새 PIN', again: '새 PIN 한 번 더' }

  const done = (pin) => {
    setError(null)
    if (step === 'old') {
      if (checkPin(pin)) setStep('new')
      else setError(lockedFor() ? null : 'PIN이 틀렸어요.')
    } else if (step === 'new') {
      setFirst(pin)
      setStep('again')
    } else if (pin === first) {
      savePin(pin)
      onDone(true)
    } else {
      setError('두 번 입력한 PIN이 달라요. 처음부터 다시 입력하세요.')
      setStep('new')
    }
  }

  return <Keypad key={step} title={titles[step]} error={error} onDone={done} onCancel={() => onDone(false)} />
}
