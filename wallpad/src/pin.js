// 월패드 PIN. 경보 해제와 '재택'으로 바꾸기(경계 풀기)에만 묻는다.
// 집에 들어온 침입자가 화면을 눌러 경보를 끄거나 경계를 푸는 것을 막기 위해서다.
// 외출/취침으로 바꾸기(경계 걸기)는 위험하지 않으니 묻지 않는다.
//
// PIN 은 이 기기 브라우저에만, 솔트 + SHA-256 반복 해시로 저장한다(평문 저장 안 함).
// crypto.subtle 은 https/localhost 에서만 되므로(폰은 http 로 붙음) SHA-256 을 직접 구현해 쓴다.
// 저장된 PIN 이 없으면 기본 1234 로 동작하고 화면에 바꾸라고 알린다.

const PIN_KEY = 'homekeeper.pin' // {"salt":"hex","hash":"hex"}
const LOCK_KEY = 'homekeeper.pinlock' // {"fails":2,"until":ms} 새로고침으로 잠금을 피하지 못하게 저장
export const DEFAULT_PIN = '1234'
export const PIN_LEN = 4
const MAX_FAIL = 3
const LOCK_SEC = 30
const ROUNDS = 2000

// ---------- SHA-256 ----------
const K = []
const H0 = []
{
  const frac = (x) => ((x - Math.floor(x)) * 2 ** 32) >>> 0
  for (let n = 2, found = 0; found < 64; n++) {
    let prime = true
    for (let d = 2; d * d <= n; d++) if (n % d === 0) prime = false
    if (!prime) continue
    if (found < 8) H0.push(frac(Math.sqrt(n)))
    K.push(frac(Math.cbrt(n)))
    found++
  }
}

export function sha256(bytes) {
  const len = bytes.length
  const total = Math.ceil((len + 9) / 64) * 64
  const m = new Uint8Array(total)
  m.set(bytes)
  m[len] = 0x80
  new DataView(m.buffer).setUint32(total - 4, len * 8)
  const h = H0.slice()
  const w = new Uint32Array(64)
  const view = new DataView(m.buffer)
  const ror = (x, n) => (x >>> n) | (x << (32 - n))
  for (let off = 0; off < total; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4)
    for (let i = 16; i < 64; i++) {
      const s0 = ror(w[i - 15], 7) ^ ror(w[i - 15], 18) ^ (w[i - 15] >>> 3)
      const s1 = ror(w[i - 2], 17) ^ ror(w[i - 2], 19) ^ (w[i - 2] >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0
    }
    let [a, b, c, d, e, f, g, hh] = h
    for (let i = 0; i < 64; i++) {
      const t1 = (hh + (ror(e, 6) ^ ror(e, 11) ^ ror(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0
      const t2 = ((ror(a, 2) ^ ror(a, 13) ^ ror(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0
      hh = g
      g = f
      f = e
      e = (d + t1) >>> 0
      d = c
      c = b
      b = a
      a = (t1 + t2) >>> 0
    }
    ;[a, b, c, d, e, f, g, hh].forEach((v, i) => (h[i] = (h[i] + v) >>> 0))
  }
  const out = new Uint8Array(32)
  h.forEach((v, i) => new DataView(out.buffer).setUint32(i * 4, v))
  return out
}

const enc = new TextEncoder()
const hex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
const unhex = (s) => new Uint8Array(s.match(/../g).map((x) => parseInt(x, 16)))
const concat = (a, b) => {
  const c = new Uint8Array(a.length + b.length)
  c.set(a)
  c.set(b, a.length)
  return c
}

export function hashPin(pin, salt) {
  let d = sha256(concat(salt, enc.encode(pin)))
  for (let i = 1; i < ROUNDS; i++) d = sha256(concat(d, salt)) // 무작위 대입을 느리게
  return hex(d)
}

// ---------- 저장 ----------
function read(key) {
  try {
    return JSON.parse(localStorage.getItem(key))
  } catch {
    return null
  }
}
function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 저장이 막힌 브라우저면 이번에만 유지
  }
}

function stored() {
  const v = read(PIN_KEY)
  return v && typeof v.salt === 'string' && typeof v.hash === 'string' ? v : null
}

export const isDefaultPin = () => !stored()

export function savePin(pin) {
  const salt = crypto.getRandomValues(new Uint8Array(16))
  write(PIN_KEY, { salt: hex(salt), hash: hashPin(pin, salt) })
}

// 잠김이 풀리기까지 남은 초 (0이면 입력 가능)
export function lockedFor(now = Date.now()) {
  const lock = read(LOCK_KEY)
  return lock?.until > now ? Math.ceil((lock.until - now) / 1000) : 0
}

// 맞으면 true. MAX_FAIL 번 틀리면 LOCK_SEC 초 잠근다
export function checkPin(pin) {
  if (lockedFor()) return false
  const s = stored()
  const salt = s ? unhex(s.salt) : enc.encode('homekeeper-default')
  const want = s ? s.hash : hashPin(DEFAULT_PIN, salt)
  if (hashPin(pin, salt) === want) {
    write(LOCK_KEY, { fails: 0, until: 0 })
    return true
  }
  const fails = (read(LOCK_KEY)?.fails ?? 0) + 1
  write(LOCK_KEY, fails >= MAX_FAIL ? { fails: 0, until: Date.now() + LOCK_SEC * 1000 } : { fails, until: 0 })
  return false
}
