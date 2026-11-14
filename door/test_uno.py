"""Pi에서 우노 연결을 확인한다. 버튼, 리모컨, 초음파 값이 화면과 LCD에 나온다. 끝내기는 Ctrl+C."""
import re
from pathlib import Path

from uno_link import Uno

CODE_FILE = Path(__file__).with_name("IR_CODES.md")
ROW = re.compile(r"^\| (.+?) \| 0x[0-9A-F]{2,4} \| (0x[0-9A-F]{2}) \|$")


def load_labels():
    if not CODE_FILE.exists():
        return {}
    labels = {}
    for line in CODE_FILE.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            labels[match[2]] = match[1]
    return labels


labels = load_labels()
uno = Uno()
print(f"Uno connected on {uno.port}. Quit: Ctrl+C")
uno.lcd(0, "PI LINK OK")
uno.lcd(1, "PRESS A BUTTON")
uno.beep(1568, 200)

buttons = 0
remote_presses = 0
distances = 0
last_distance = None
try:
    while True:
        line = uno.read_line()
        if line is None:
            continue
        if line == "BTN":
            buttons += 1
            print(f"[BUTTON] pressed ({buttons})")
            uno.beep(2093, 80)
            uno.lcd(1, f"BUTTON {buttons}")
        elif line.startswith("IR:"):
            remote_presses += 1
            code = line[3:]
            label = labels.get(code, code)
            print(f"[REMOTE] {label}")
            uno.lcd(1, f"REMOTE {label}")
        elif line.startswith("DIST:"):
            distances += 1
            value = int(line[5:])
            if value != last_distance and distances % 3 == 0:
                print("[DISTANCE] " + ("no echo" if value < 0 else f"{value} cm"))
                last_distance = value
except KeyboardInterrupt:
    pass
finally:
    print("\n--- Result ---")
    print("LCD     : OK if the screen shows PI LINK OK")
    print(f"Button  : {'OK' if buttons else 'not pressed'} ({buttons})")
    print(f"Remote  : {'OK' if remote_presses else 'no signal'} ({remote_presses})")
    print(f"Distance: {'OK' if last_distance is not None and last_distance >= 0 else 'no reading'}")
    uno.close()
