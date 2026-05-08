# Luna Minecraft Discord Bot

디스코드 slash command로 마인크래프트 서버를 켜고, RCON으로 상태 확인/종료/명령 실행을 하는 봇입니다. Python 의존성 관리는 `uv`를 사용합니다.

## 기능

- `/mc start` - `.env`에 적은 시작 명령으로 서버 실행
- `/mc stop` - RCON `stop`으로 서버 안전 종료
- `/mc status` - RCON `list`로 서버 응답 확인
- `/mc whitelist-add player:<닉네임>` - 플레이어를 화이트리스트에 추가
- `/mc rcon command:<명령어>` - 허용된 사람만 RCON 명령 실행

## 마인크래프트 RCON 설정

서버의 `server.properties`에 아래 값을 설정하세요.

```properties
enable-rcon=true
rcon.port=25575
rcon.password=강한비밀번호
```

수정 후에는 마인크래프트 서버를 재시작해야 적용됩니다.

## 디스코드 봇 준비

1. Discord Developer Portal에서 Application과 Bot을 만듭니다.
2. Bot token을 복사해서 `.env`의 `DISCORD_TOKEN`에 넣습니다.
3. OAuth2 URL Generator에서 `bot`, `applications.commands` scope를 체크하고 서버에 초대합니다.
4. 권한은 최소한 slash command 응답을 보낼 수 있으면 됩니다.

서버/유저/역할 ID를 복사하려면 Discord 설정에서 Developer Mode를 켠 뒤 우클릭해서 Copy ID를 사용하세요.

## 설치

Windows PowerShell 기준:

```powershell
uv sync
Copy-Item .env.example .env
```

그 다음 `.env`를 열어서 값들을 실제 환경에 맞게 바꿉니다.

## run.sh로 서버를 켜는 경우

`./run.sh` 자체가 시작 커맨드입니다. 봇은 `MINECRAFT_SERVER_DIR`로 이동한 뒤 `MINECRAFT_START_COMMAND`를 실행합니다.

Linux나 WSL 안에서 봇도 같이 실행한다면:

```env
MINECRAFT_SERVER_DIR=/home/minecraft/server
MINECRAFT_START_COMMAND=./run.sh
```

`run.sh` 실행 권한이 없다면 서버 폴더에서 한 번만 실행하세요.

```bash
chmod +x run.sh
```

Windows에서 Git Bash의 `bash`로 `.sh`를 실행해야 한다면:

```env
MINECRAFT_SERVER_DIR=C:\minecraft\server
MINECRAFT_START_COMMAND=bash ./run.sh
```

`run.sh`는 서버 프로세스를 백그라운드로 넘기지 말고, 보통의 `java ... nogui`처럼 계속 떠 있는 방식이어야 로그 추적과 상태 확인이 자연스럽습니다.

## .env 예시

```env
DISCORD_TOKEN=여기에_봇_토큰
DISCORD_GUILD_ID=디스코드_서버_ID
DISCORD_ALLOWED_USER_IDS=내_디스코드_유저_ID
ALLOW_DISCORD_ADMINS=false

MINECRAFT_SERVER_DIR=/home/minecraft/server
MINECRAFT_START_COMMAND=./run.sh
MINECRAFT_RCON_HOST=127.0.0.1
MINECRAFT_RCON_PORT=25575
MINECRAFT_RCON_PASSWORD=server.properties와_같은_비밀번호
```

## 실행

```powershell
uv run python bot.py
```

처음 실행하면 봇 콘솔에 slash command 동기화 로그가 찍힙니다. `DISCORD_GUILD_ID`를 넣어두면 보통 바로 보이고, 비워두면 global command라 Discord에 반영되기까지 시간이 걸릴 수 있습니다.

## 봇 명령 사용 로그

systemd로 실행 중이면 누가 어떤 slash command를 썼는지 아래 명령으로 확인할 수 있습니다.

```bash
journalctl -u luna-minecraft-bot -f
```

명령 사용 로그만 보고 싶으면:

```bash
journalctl -u luna-minecraft-bot | grep 'Command '
```

로그에는 Discord 유저명, 유저 ID, 서버 ID, 채널 ID, 실행한 명령과 옵션이 남습니다. `/mc rcon`에 입력한 RCON 명령도 감사 로그에 남습니다.

## uv 설치가 안 되어 있을 때

Windows에서는 아래 명령으로 설치할 수 있습니다.

```powershell
winget install --id Astral.UV
```

설치 후 새 PowerShell을 열고 `uv --version`으로 확인하세요.

## 보안 메모

RCON은 서버 콘솔 권한과 거의 같습니다. `DISCORD_ALLOWED_USER_IDS`나 `DISCORD_ALLOWED_ROLE_IDS`로 사용할 사람을 꼭 제한하세요. `ALLOW_DISCORD_ADMINS=true`는 개인/소규모 서버에서만 추천합니다.

또한 RCON 포트는 가능하면 외부 인터넷에 열지 말고 `127.0.0.1` 또는 내부망에서만 접근하게 두는 편이 좋습니다.
