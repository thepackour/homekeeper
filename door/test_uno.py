"""Pi에서 우노 연결을 확인한다. 버튼, 리모컨, 카드, 초음파 값이 화면과 LCD에 나온다. 끝내기는 Ctrl+C."""
import argparse

from uno_link import Uno, load_ir_labels

parser = argparse.ArgumentParser(description="Check the Uno parts")
parser.add_argument("--port", help="Uno serial port (e.g. COM5). Found automatically if omitted")
args = parser.parse_args()

labels = load_ir_labels()
uno = Uno(args.port)
print(f"Uno connected on {uno.port}. Quit: Ctrl+C")
uno.lcd(0, "PI LINK OK")
uno.lcd(1, "PRESS A BUTTON")
uno.beep(1568, 200)

buttons = 0
remote_presses = 0
cards = 0
distances = 0
good_distances = 0
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
        elif line.startswith("CARD:"):
            cards += 1
            print(f"[CARD] {line[5:]}")
            uno.beep(1568, 120)
            uno.lcd(1, line)
        elif line.startswith("DIST:"):
            distances += 1
            value = int(line[5:])
            if value >= 0:
                good_distances += 1
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
    print(f"Card    : {'OK' if cards else 'no card'} ({cards})")
    print(f"Distance: {'OK' if good_distances else 'no reading'} ({good_distances} readings)")
    uno.close()
