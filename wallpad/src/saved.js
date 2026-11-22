// 로그인 정보와 브로커 주소를 이 기기(브라우저)에만 저장한다. 코드에는 비밀번호를 넣지 않는다.
import { DEFAULT_BROKERS } from './config'

const LOGIN_KEY = 'homekeeper.login' // {"user":"wallpad","password":"..."}
const BROKERS_KEY = 'homekeeper.brokers' // ["hub.local","door.local"]

function read(key) {
  try {
    return JSON.parse(localStorage.getItem(key))
  } catch {
    return null
  }
}

function write(key, value) {
  try {
    if (value == null) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 저장이 막힌 브라우저면 이번에만 쓰고 다음엔 다시 묻는다
  }
}

export function loadLogin() {
  const v = read(LOGIN_KEY)
  return v && typeof v.user === 'string' && typeof v.password === 'string' ? v : null
}

export const saveLogin = (login) => write(LOGIN_KEY, login)

export function loadBrokers() {
  const v = read(BROKERS_KEY)
  return Array.isArray(v) && v.length === 2 && v.every((s) => typeof s === 'string') ? v : DEFAULT_BROKERS
}

export const saveBrokers = (brokers) => write(BROKERS_KEY, brokers)
