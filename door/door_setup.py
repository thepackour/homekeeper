"""현관 카드와 비밀번호 등록. 저장은 door_data.json (GitHub에 올리지 않음).

python door_setup.py card sihoon            # 우노 카드 리더에 카드를 대면 등록
python door_setup.py card sihoon --uid A1B2C3D4   # 카드 번호를 직접 입력 (우노 없이 시험할 때)
python door_setup.py password                # 리모컨으로 누를 숫자 비밀번호 (4~8자리)
python door_setup.py list
python door_setup.py remove A1B2C3D4

비밀번호는 그대로 저장하지 않고 소금(salt)을 섞은 해시만 저장한다.
"""
import argparse
import getpass
import hashlib
import hmac
import json
import re
import secrets
from pathlib import Path
from time import monotonic

DATA_FILE = Path(__file__).with_name("door_data.json")
HASH_ROUNDS = 60_000
CARD_WAIT_SEC = 30


def load_data(path=DATA_FILE):
    if not path.exists():
        return {"cards": {}, "password": None}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("cards", {})
    data.setdefault("password", None)
    return data


def save_data(data, path=DATA_FILE):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), HASH_ROUNDS).hex()


def make_password(password):
    salt = secrets.token_hex(16)
    return {"salt": salt, "hash": _hash(password, salt)}


def check_password(password, data):
    stored = data.get("password")
    if not stored:
        return False
    return hmac.compare_digest(_hash(password, stored["salt"]), stored["hash"])


def read_card(port=None):
    from uno_link import Uno

    uno = Uno(port)
    uno.lcd(0, "CARD SETUP")
    uno.lcd(1, "TAP A CARD")
    print("Tap a card on the reader...")
    deadline = monotonic() + CARD_WAIT_SEC
    try:
        while monotonic() < deadline:
            line = uno.read_line()
            if line and line.startswith("CARD:"):
                uid = line[5:]
                uno.lcd(1, f"SAVED {uid}")
                uno.beep(1568, 150)
                return uid
    finally:
        uno.close()
    raise SystemExit("No card within 30 seconds")


def main():
    parser = argparse.ArgumentParser(description="Register door cards and the remote password")
    sub = parser.add_subparsers(dest="command", required=True)
    card = sub.add_parser("card", help="register a card")
    card.add_argument("name", help="owner name (English, same as the face name)")
    card.add_argument("--uid", help="card number, if you already know it")
    card.add_argument("--port", help="Uno serial port (e.g. COM5)")
    sub.add_parser("password", help="set the remote password")
    sub.add_parser("list", help="show cards")
    remove = sub.add_parser("remove", help="remove a card")
    remove.add_argument("uid")
    args = parser.parse_args()

    data = load_data()
    if args.command == "card":
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
            parser.error("Use only English letters, numbers, _ or - in the name")
        uid = (args.uid or read_card(args.port)).upper()
        if not re.fullmatch(r"[0-9A-F]{8,20}", uid):
            parser.error(f"Not a card number: {uid}")
        data["cards"][uid] = args.name
        save_data(data)
        print(f"Saved card {uid} for {args.name}")
    elif args.command == "password":
        first = getpass.getpass("New password (4-8 digits): ")
        if not re.fullmatch(r"\d{4,8}", first):
            raise SystemExit("Use 4 to 8 digits (the remote only has numbers)")
        if getpass.getpass("Again: ") != first:
            raise SystemExit("Passwords did not match. Nothing saved")
        data["password"] = make_password(first)
        save_data(data)
        print("Password saved")
    elif args.command == "list":
        for uid, name in data["cards"].items():
            print(f"{uid}  {name}")
        print(f"{len(data['cards'])} card(s). Password: {'set' if data['password'] else 'NOT SET'}")
    elif args.command == "remove":
        if data["cards"].pop(args.uid.upper(), None) is None:
            raise SystemExit(f"No card {args.uid}")
        save_data(data)
        print(f"Removed {args.uid.upper()}")


if __name__ == "__main__":
    main()
