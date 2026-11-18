"""우노 없이 노트북에서 현관 프로그램을 시험할 때 쓰는 가짜 우노. 키보드로 부품 입력을 흉내 낸다.

입력 예: card A1B2C3D4 / 1234 (리모컨 숫자) / ok (CONFIRM) / del (DELETE) / btn (나가기 버튼)
         dist 30 (초음파 30cm 계속) / dist off / sleep 2 / quit
"""
import _thread
import queue
import sys
import threading
import time

from uno_link import load_ir_labels

DISTANCE_INTERVAL_SEC = 0.3

HELP = """[FAKE UNO] type commands and press Enter:
  card A1B2C3D4   tap a card
  1234            remote digits      ok = CONFIRM, del = DELETE
  btn             exit button        dist 30 / dist off = ultrasonic
  sleep 2         wait (for scripts) quit = stop"""


class FakeUno:
    port = "keyboard"

    def __init__(self, echo=True):
        codes = {label: code for code, label in load_ir_labels().items()}
        self.keys = {**{d: codes[d] for d in "0123456789" if d in codes},
                     "ok": codes.get("CONFIRM"), "del": codes.get("DELETE")}
        self.lines = queue.Queue()
        self.distance = -1
        self.echo = echo
        threading.Thread(target=self._keyboard, daemon=True).start()
        threading.Thread(target=self._distance_loop, daemon=True).start()
        print(HELP, flush=True)

    def _keyboard(self):
        for raw in sys.stdin:
            words = raw.split()
            if not words:
                continue
            command = words[0].lower()
            if command == "quit":
                break
            if command == "card" and len(words) > 1:
                self.lines.put(f"CARD:{words[1].upper()}")
            elif command == "btn":
                self.lines.put("BTN")
            elif command == "dist" and len(words) > 1:
                self.distance = -1 if words[1] == "off" else int(words[1])
            elif command == "sleep" and len(words) > 1:
                time.sleep(float(words[1]))
            elif command in ("ok", "del"):
                self.lines.put(f"IR:{self.keys[command]}")
            elif command.isdigit():
                for digit in command:
                    self.lines.put(f"IR:{self.keys[digit]}")
            else:
                print(f"[FAKE UNO] unknown command: {raw.strip()}", flush=True)
        _thread.interrupt_main()  # 입력이 끝나면 프로그램도 끝낸다 (Ctrl+C와 같음)

    def _distance_loop(self):
        while True:
            time.sleep(DISTANCE_INTERVAL_SEC)
            self.lines.put(f"DIST:{self.distance}")

    def read_line(self):
        try:
            return self.lines.get(timeout=0.05)
        except queue.Empty:
            return None

    def lcd(self, line, text):
        if self.echo:
            print(f"[LCD{line}] {text[:16]}", flush=True)

    def beep(self, frequency, milliseconds):
        if self.echo:
            print(f"[BEEP] {frequency}Hz {milliseconds}ms", flush=True)

    def close(self):
        pass
