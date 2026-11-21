# 홈키파 앱 화면

월패드와 폰이 같이 쓰는 웹 화면 (Vite + React + mqtt.js).
토픽과 메시지는 팀 저장소 `docs/mqtt.md` 규약을 그대로 따른다. 규약에 없는 토픽은 쓰지 않는다.

## 화면이 하는 일

- **의심 단계 띠**: `home/state/suspicion` 값만 따라간다(retain이라 새로고침해도 유지).
  0 정상(초록) / 1 주의, 문 앞 서성임(노랑) / 2 경고, 서성임 30초 이상 또는 외출 중 문 열림 후 30초 내 미인증(주황) / 3 경보, 꼬리물기(빨강).
  단계 2 이상이면 **경보 해제** 버튼이 나온다.
- **기기 상태 줄**: `home/status/<노드>`를 보고, `{"alive":0}`(LWT)이 오거나 3초 넘게 신호가 없으면 "거실 응답 없음"처럼 빨갛게 표시. 오른쪽은 판단 담당(`home/state/judge`).
- **현관 칸**: 방문자 사진(`home/door/visitor`), 서성임 상태(`home/door/loiter`), 마지막 문 열림(`home/door/open`), 마지막 인증의 위험 점수(`home/door/auth`), **출입 허락** 버튼.
- **월패드 계정이면** 1초마다 `home/status/wallpad {"alive":1}`을 보내고, LWT `{"alive":0}`을 걸어 둔다. 폰은 규약 목록에 없어서 보내지 않는다.

## 보낸 명령 확인 · PIN

- **명령 ≠ 상태**: 모드 버튼을 누르면 "바꾸는 중…"으로 두고, 허브가 `home/state/mode`로 확정해야 바뀐다. 경보 해제도 의심 단계가 내려가야 끝. 3초 안에 안 오면 기록에 "허브 응답 없음".
- **출입 허락**: 허브 브로커와 현관 직통(`src/direct.js`, 예비 주소로 따로 붙은 연결) 둘 다로 보낸다. 허브 브로커가 끊겨도 직통이 붙어 있으면 허락 버튼은 살아 있다. 현관이 `door/open {"by":"approve"}`를 보내면 "문 열림 확인", 5초 안에 없으면 "현관 응답 없음". 규약은 `docs/mqtt.md` 출입 허락 항목.
- **PIN**: 경보 해제, 외출·취침 → 재택(경계 풀기)에만 묻는다. 기본 1234, 설정 → PIN 바꾸기. 기기 브라우저에 솔트+SHA-256 반복 해시로만 저장, 3번 틀리면 30초 잠김.
- 시험: 브로커를 하나 더(`mosquitto -c mosquitto-dev-door.conf -v`) 켜고 로그인 예비 주소를 `localhost:9002`로. `node tools/fake.mjs answer --door mqtt://localhost:1884`가 허브·현관처럼 답한다(같은 id 중복 무시까지).

## 처음 켤 때 (로그인)

계정(월패드 `wallpad` / 폰 `phone`)과 비밀번호, 브로커 주소를 입력한다.

- 비밀번호는 코드에 없고, **그 기기의 브라우저에만** 저장된다(localStorage). 오른쪽 위 **설정 → 로그아웃**하면 지워진다.
- 비밀번호가 틀리면 로그인 화면으로 돌아가 빨간 "로그인 실패"가 뜬다. 브로커가 꺼진 것(위쪽 "연결 끊김")과는 다르게 표시된다.
- 브로커 주소: 코드에 적지 않고 저장소 `common/config.json`(주 `hub.local`, 예비 `door.local`)을 빌드할 때 읽어 온다(`vite.config.js`).
  포트만 WebSocket용 9001로 바꿔 붙는다. 이름만 쓰면 9001, 다른 포트는 `이름:포트`로 쓴다. 설정에서 언제든 바꿀 수 있다.
  저장소 밖에서 실행해 `common/config.json`이 없으면 주소 칸이 비어 있으니 직접 넣는다.
- 주 브로커가 3초 끊기면 예비로 넘어가고, **자동으로 돌아가지 않는다**(공통 모듈과 같음). 돌아갈 때는 설정의 **주 브로커로 돌아가기**.
  3초와 1초(살아 있음 주기)도 `common/config.json`의 `failover_sec`, `heartbeat_sec`를 따른다.
- 허브, 현관 브로커(`broker/mosquitto.conf`)에 WebSocket 9001 리스너가 있어야 화면이 붙는다. 계정, 권한은 1883과 똑같이 적용된다.

## 노트북에서 실행

1. 브로커 켜기 (터미널 1, 이 폴더의 `mosquitto-dev.conf`: 1883 + WebSocket 9001, 로그인 없음, 노트북 안에서만)

   ```powershell
   $env:Path += ";C:\Program Files\mosquitto"
   mosquitto -c mosquitto-dev.conf -v
   ```

   mosquitto Windows 서비스가 1883 포트를 잡고 있으면 먼저 관리자 PowerShell에서 `net stop mosquitto`.

2. 화면 켜기 (터미널 2)

   ```powershell
   npm install
   npm run dev
   ```

   http://localhost:5173 을 열고, 로그인 화면에서 브로커 주 주소를 `localhost`로 바꾼다(비밀번호는 아무거나).

3. 가짜 메시지 보내기 (터미널 3). `tools/fake.mjs`가 허브, 현관을 흉내 낸다. `"t"`는 자동으로 붙는다.

   ```powershell
   node tools/fake.mjs level 1                 # 의심 단계 0~3
   node tools/fake.mjs mode away               # home, away, sleep
   node tools/fake.mjs people 2                # 집 안 인원
   node tools/fake.mjs judge door              # 판단 담당
   node tools/fake.mjs loiter start            # start, over30, end
   node tools/fake.mjs visitor C:\Windows\Web\Screen\img105.jpg   # 방문자 사진
   node tools/fake.mjs open auth               # 문 열림
   node tools/fake.mjs auth ok 2 card+pw none  # 현관 인증 결과 (위험 점수)
   node tools/fake.mjs pwfail 1                # 현관 비밀번호 틀림
   node tools/fake.mjs alert 3 tailgate        # 경보
   node tools/fake.mjs alive door living hub   # 노드 살아 있음 (Ctrl+C로 끊으면 "응답 없음")
   node tools/fake.mjs watch                   # 화면이 보내는 명령 보기
   ```

   다른 브로커는 `--broker mqtt://주소:1883`, 비밀번호가 있으면 `--user hub --pass 비밀번호`.
   사진은 작게(수십 KB) 보낸다. 노트북 mosquitto 2.1은 2MB 정도 사진을 "oversize packet"으로 끊었다.

   mosquitto_pub로 직접 보낼 때(PowerShell 5.1): JSON 따옴표는 `\"`, 띄어쓰기 없이.

   ```powershell
   mosquitto_pub -t home/state/suspicion -r -m '{\"level\":2}'
   ```

## 비밀번호, 권한(ACL) 테스트

빈 폴더에 저장소 `broker/homekeeper.acl`을 복사해 오고, 그 폴더에서 테스트용 계정을 만든다.
`WALLPAD_PW`, `HUB_PW` 자리에는 직접 정한 테스트 비밀번호를 넣는다(영어로. 한글은 PowerShell에서 깨진다).

```powershell
$env:Path += ";C:\Program Files\mosquitto"
mosquitto_passwd -c -b homekeeper.passwd wallpad WALLPAD_PW
mosquitto_passwd -b homekeeper.passwd hub HUB_PW
```

`test-auth.conf`:

```
listener 1893 localhost
listener 9103 localhost
protocol websockets
allow_anonymous false
password_file homekeeper.passwd
acl_file homekeeper.acl
```

파일 경로는 위처럼 상대 경로로 쓰고 **그 폴더에서** `mosquitto -c test-auth.conf -v`로 켠다(한글이 들어간 절대 경로는 mosquitto가 못 연다).
화면에서 주 주소 `localhost:9103`, wallpad 계정으로 로그인하고,
`node tools/fake.mjs watch --broker mqtt://localhost:1893 --user hub --pass HUB_PW`로 명령이 도착하는지 본다.
명령이 권한 때문에 막히면 화면 기록에 "실패: 권한 없음"이 남는다.

## 토픽 (docs/mqtt.md)

토픽 이름은 전부 `src/config.js`에 있다.

| 방향 | 토픽 | 내용 |
|---|---|---|
| 받음 | `home/state/mode` | `{"mode":"home"}` home / away / sleep |
| 받음 | `home/state/occupancy` | `{"n":2}` 집 안 인원 |
| 받음 | `home/state/suspicion` | `{"level":0}` 의심 단계 0~3 |
| 받음 | `home/state/judge` | `{"node":"hub"}` 판단 담당 |
| 받음 | `home/alert` | `{"level":3,"type":"tailgate"}` (retain 아님) |
| 받음 | `home/door/open` | `{"state":"open","by":"auth"}` by: auth(인증) / approve(원격 허락) |
| 받음 | `home/door/loiter` | `{"state":"start"}` → `over30` → `end` |
| 받음 | `home/door/visitor` | `{"img":"base64"}` 방문자 사진 |
| 받음 | `home/door/auth` | `{"result":"ok","method":"card+pw","face":"match","score":2}` 마지막 인증, 위험 점수 |
| 받음 | `home/door/pwfail` | `{"count":2}` 비밀번호 틀림 (기록에만) |
| 받음 | `home/status/+` | `{"alive":1}` 1초마다, 끊기면 `{"alive":0}` |
| 보냄 | `home/cmd/mode` | `{"mode":"away"}` |
| 보냄 | `home/cmd/approve` | `{"ok":1}` 출입 허락 (현관이 직접 듣고 문을 연다) |
| 보냄 | `home/cmd/dismiss` | `{}` 경보 해제 (단계 2 이상일 때만) |
| 보냄 | `home/status/wallpad` | `{"alive":1}` 1초마다 (월패드 계정만), LWT `{"alive":0}` |

- 보내는 메시지에는 모두 `"t"`(보낸 시각, 초, 소수 3자리)가 붙는다. 단 LWT는 공통 모듈처럼 `{"alive":0}`만(미리 맡겨 두는 메시지라 시각을 알 수 없음).
- 명령은 QoS 1, 살아 있음은 QoS 0 + retain.
- 화면에 보이는 시각은 메시지의 `"t"`가 아니라 화면이 받은 시각이다(핫스팟에 인터넷이 없으면 Pi 시계가 틀릴 수 있어서).
