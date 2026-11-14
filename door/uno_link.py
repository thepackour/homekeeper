"""Pi와 우노를 USB 시리얼로 잇는 코드. 부품은 우노가 다루고 Pi는 메시지만 주고받는다."""
import glob
from time import monotonic

import serial

BAUD_RATE = 9600
READY_TIMEOUT_SEC = 6


class Uno:
    def __init__(self, port=None):
        ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
        self.port = port or (ports[0] if ports else None)
        if self.port is None:
            raise SystemExit("Uno not found. Check the USB cable")
        self.serial = serial.Serial(self.port, BAUD_RATE, timeout=0.05)
        self.buffer = b""

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

    def lcd(self, line, text):
        self.serial.write(f"LCD{line}:{text}\n".encode("ascii", "replace"))

    def beep(self, frequency, milliseconds):
        self.serial.write(f"BEEP:{frequency},{milliseconds}\n".encode("ascii"))

    def close(self):
        self.serial.close()
