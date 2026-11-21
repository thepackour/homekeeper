"""Pi와 우노를 USB 시리얼로 잇는 코드. 부품은 우노가 다루고 Pi는 메시지만 주고받는다."""
import glob
import re
from pathlib import Path
from time import monotonic, sleep

import serial

BAUD_RATE = 9600
READY_TIMEOUT_SEC = 6
LCD_WIDTH = 16
CODE_FILE = Path(__file__).with_name("IR_CODES.md")
CODE_ROW = re.compile(r"^\| (.+?) \| 0x[0-9A-F]{2,4} \| (0x[0-9A-F]{2}) \|$")


def load_ir_labels():
    """IR_CODES.md 표를 읽어 {"0x0C": "1", ...}로 돌려준다."""
    if not CODE_FILE.exists():
        return {}
    labels = {}
    for line in CODE_FILE.read_text(encoding="utf-8").splitlines():
        match = CODE_ROW.match(line)
        if match:
            labels[match[2]] = match[1]
    return labels


def find_port():
    """Pi에서는 /dev/ttyACM0 같은 이름, 노트북(Windows)에서는 우노로 보이는 COM 포트를 찾는다."""
    ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    if ports:
        return ports[0]
    from serial.tools import list_ports

    for port in list_ports.comports():
        if any(word in (port.description or "") for word in ("Arduino", "CH340", "USB")):
            return port.device
    return None


class Uno:
    def __init__(self, port=None):
        self.port = port or find_port()
        if self.port is None:
            raise SystemExit("Uno not found. Check the USB cable")
        self.serial = serial.Serial(self.port, BAUD_RATE, timeout=0.05)
        self.buffer = b""
        self.busy_until = 0.0

        # 시리얼을 열면 우노가 다시 시작되므로 준비될 때까지 기다린다.
        deadline = monotonic() + READY_TIMEOUT_SEC
        while monotonic() < deadline:
            if self.read_line() == "READY":
                return
        self.close()
        raise SystemExit("No READY from the Uno. Upload door_uno.ino first")

    def read_line(self):
        """우노가 보낸 한 줄을 돌려준다. 아직 없으면 None."""
        self.buffer += self.serial.read(self.serial.in_waiting or 1)
        if b"\n" not in self.buffer:
            return None
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode("ascii", "ignore").strip()

    def _send(self, text):
        # 우노는 부저가 울리는 동안 메시지를 못 읽는다. 받는 칸(64바이트)이 넘치지 않게 끝날 때까지 기다린다.
        wait = self.busy_until - monotonic()
        if wait > 0:
            sleep(wait)
        self.serial.write(f"{text}\n".encode("ascii", "replace"))

    def lcd(self, line, text):
        self._send(f"LCD{line}:{text[:LCD_WIDTH]}")

    def beep(self, frequency, milliseconds):
        self._send(f"BEEP:{frequency},{milliseconds}")
        self.busy_until = monotonic() + milliseconds / 1000 + 0.02

    def door(self, open_):
        """서보로 문을 연다(True) / 잠근다(False). 각도는 우노 코드 맨 위에서 정한다."""
        self._send("DOOR:OPEN" if open_ else "DOOR:LOCK")

    def close(self):
        self.serial.close()
