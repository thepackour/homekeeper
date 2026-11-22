// 화면 안쪽을 끌어서 스크롤하기.
// 월패드의 저항막 터치(Waveshare 4인치)는 리눅스에서 마우스처럼 들어와서, 손가락으로 끌어도 스크롤되지 않고
// 화면 가장자리의 스크롤바는 터치가 잘 먹지 않는다. 그래서 스크롤 가능한 칸 안을 끌면 그 칸이 움직이게 한다.
// 8px 넘게 끌었으면 손을 뗄 때의 클릭은 버린다(끌다가 버튼이 눌리지 않게).
// 폰처럼 진짜 터치(pointerType 'touch')는 브라우저가 알아서 하므로 건드리지 않는다.
const THRESHOLD = 8

function scrollableParent(el) {
  for (; el && el !== document.documentElement; el = el.parentElement) {
    const { overflowY } = getComputedStyle(el)
    if ((overflowY === 'auto' || overflowY === 'scroll') && el.scrollHeight > el.clientHeight) return el
  }
  const root = document.scrollingElement
  return root && root.scrollHeight > root.clientHeight ? root : null
}

export function enableDragScroll() {
  let drag = null // {el, y, top, moved}

  document.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'touch' || e.button !== 0) return
    if (e.target.closest('input, textarea, select')) return
    const el = scrollableParent(e.target)
    if (el) drag = { el, y: e.clientY, top: el.scrollTop, moved: false }
  })

  document.addEventListener('pointermove', (e) => {
    if (!drag) return
    const dy = e.clientY - drag.y
    if (!drag.moved && Math.abs(dy) < THRESHOLD) return
    drag.moved = true
    drag.el.scrollTop = drag.top - dy
  })

  const end = () => {
    if (drag?.moved) {
      // 끌기가 끝난 직후 한 번 오는 클릭은 버튼을 누른 게 아니다
      const block = (ev) => {
        ev.stopPropagation()
        ev.preventDefault()
      }
      window.addEventListener('click', block, { capture: true, once: true })
      setTimeout(() => window.removeEventListener('click', block, { capture: true }), 50)
    }
    drag = null
  }
  document.addEventListener('pointerup', end)
  document.addEventListener('pointercancel', end)
}
