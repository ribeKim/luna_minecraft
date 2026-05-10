import asyncio
import logging
import os
import re
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


LOGGER = logging.getLogger("luna_minecraft_bot")
MINECRAFT_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,16}$")
RCON_AUTH = 3
RCON_COMMAND = 2


class UserFacingError(Exception):
    """Error message that is safe to show in Discord."""


def parse_int_set(raw_value: str) -> set[int]:
    values: set[int] = set()
    for item in raw_value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.add(int(item))
        except ValueError as exc:
            raise UserFacingError(f"ID 값이 숫자가 아닙니다: `{item}`") from exc
    return values


def parse_bool(raw_value: str, default: bool = False) -> bool:
    if raw_value == "":
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_optional_int(raw_value: str, name: str) -> int | None:
    raw_value = raw_value.strip()
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except ValueError as exc:
        raise UserFacingError(f"`{name}` 값은 숫자여야 합니다: `{raw_value}`") from exc


def parse_required_int(raw_value: str, name: str) -> int:
    try:
        return int(raw_value)
    except ValueError as exc:
        raise UserFacingError(f"`{name}` 값은 숫자여야 합니다: `{raw_value}`") from exc


def parse_required_float(raw_value: str, name: str) -> float:
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise UserFacingError(f"`{name}` 값은 숫자여야 합니다: `{raw_value}`") from exc
    if value <= 0:
        raise UserFacingError(f"`{name}` 값은 0보다 커야 합니다: `{raw_value}`")
    return value


def clean_command(command: str) -> str:
    return command.strip().removeprefix("/").strip()


def clean_minecraft_username(username: str) -> str:
    username = username.strip()
    if not MINECRAFT_USERNAME_PATTERN.fullmatch(username):
        raise UserFacingError("Minecraft 닉네임은 영문, 숫자, 밑줄 3-16자만 가능합니다.")
    return username


def discord_code_block(text: str) -> str:
    if not text:
        text = "(응답 없음)"
    text = text.replace("```", "`\u200b``")
    if len(text) > 1750:
        text = text[:1750] + "\n...응답이 길어서 잘랐습니다."
    return f"```text\n{text}\n```"


def summarize_interaction_command(interaction: discord.Interaction) -> str:
    data = interaction.data if isinstance(interaction.data, dict) else {}
    parts: list[str] = []
    option_parts: list[str] = []

    def walk(node: dict) -> None:
        name = node.get("name")
        if name:
            parts.append(str(name))

        for option in node.get("options", []) or []:
            option_name = str(option.get("name", "unknown"))
            if "value" in option:
                value = option["value"]
                if any(secret in option_name.lower() for secret in ("password", "secret", "token")):
                    value = "[redacted]"
                option_parts.append(f"{option_name}={value!r}")
            else:
                walk(option)

    walk(data)

    if parts:
        command = "/" + " ".join(parts)
    elif interaction.command:
        command = "/" + interaction.command.qualified_name
    else:
        command = "/unknown"

    if option_parts:
        return f"{command} {' '.join(option_parts)}"
    return command


def log_command_event(interaction: discord.Interaction, event: str, command: str, detail: str = "") -> None:
    user = interaction.user
    LOGGER.info(
        "Command %s: user=%s user_id=%s guild_id=%s channel_id=%s command=%s%s",
        event,
        user,
        user.id,
        interaction.guild_id,
        interaction.channel_id,
        command,
        f" detail={detail}" if detail else "",
    )


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    allowed_user_ids: set[int]
    allowed_role_ids: set[int]
    allow_discord_admins: bool
    minecraft_server_dir: Path
    minecraft_start_command: str
    minecraft_log_file: Path
    startup_check_seconds: int
    shutdown_check_seconds: int
    rcon_host: str
    rcon_port: int
    rcon_password: str
    rcon_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise UserFacingError("`.env`에 `DISCORD_TOKEN`을 설정해야 합니다.")

        guild_id = parse_optional_int(os.getenv("DISCORD_GUILD_ID", ""), "DISCORD_GUILD_ID")

        server_dir = Path(os.getenv("MINECRAFT_SERVER_DIR", ".")).expanduser().resolve()
        log_file_raw = os.getenv("MINECRAFT_LOG_FILE", "bot-server.log").strip()
        log_file = Path(log_file_raw).expanduser()
        if not log_file.is_absolute():
            log_file = server_dir / log_file

        return cls(
            discord_token=token,
            discord_guild_id=guild_id,
            allowed_user_ids=parse_int_set(os.getenv("DISCORD_ALLOWED_USER_IDS", "")),
            allowed_role_ids=parse_int_set(os.getenv("DISCORD_ALLOWED_ROLE_IDS", "")),
            allow_discord_admins=parse_bool(os.getenv("ALLOW_DISCORD_ADMINS", ""), default=False),
            minecraft_server_dir=server_dir,
            minecraft_start_command=os.getenv("MINECRAFT_START_COMMAND", "").strip(),
            minecraft_log_file=log_file.resolve(),
            startup_check_seconds=parse_required_int(os.getenv("STARTUP_CHECK_SECONDS", "90"), "STARTUP_CHECK_SECONDS"),
            shutdown_check_seconds=parse_required_int(os.getenv("SHUTDOWN_CHECK_SECONDS", "45"), "SHUTDOWN_CHECK_SECONDS"),
            rcon_host=os.getenv("MINECRAFT_RCON_HOST", "127.0.0.1").strip(),
            rcon_port=parse_required_int(os.getenv("MINECRAFT_RCON_PORT", "25575"), "MINECRAFT_RCON_PORT"),
            rcon_password=os.getenv("MINECRAFT_RCON_PASSWORD", "").strip(),
            rcon_timeout_seconds=parse_required_float(os.getenv("RCON_TIMEOUT_SECONDS", "5"), "RCON_TIMEOUT_SECONDS"),
        )


def read_exact(sock: socket.socket, length: int) -> bytes:
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("RCON 연결이 끊겼습니다.")
        data += chunk
    return data


def send_rcon_packet(sock: socket.socket, request_id: int, packet_type: int, payload: str) -> None:
    payload_bytes = payload.encode("utf-8")
    body = struct.pack("<ii", request_id, packet_type) + payload_bytes + b"\x00\x00"
    sock.sendall(struct.pack("<i", len(body)) + body)


def read_rcon_packet(sock: socket.socket) -> tuple[int, int, str]:
    length = struct.unpack("<i", read_exact(sock, 4))[0]
    if length < 10:
        raise ConnectionError(f"잘못된 RCON 패킷 길이입니다: {length}")

    body = read_exact(sock, length)
    request_id, packet_type = struct.unpack("<ii", body[:8])
    payload = body[8:-2].decode("utf-8", errors="replace")
    return request_id, packet_type, payload


class MinecraftController:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def rcon(self, command: str) -> str:
        command = clean_command(command)
        if not command:
            raise UserFacingError("실행할 RCON 명령어를 입력해야 합니다.")
        if not self.settings.rcon_password:
            raise UserFacingError("`.env`에 `MINECRAFT_RCON_PASSWORD`를 설정해야 RCON을 쓸 수 있습니다.")

        return await asyncio.to_thread(self._rcon_sync, command)

    async def whitelist_add(self, player: str) -> str:
        player = clean_minecraft_username(player)
        response = await self.rcon(f"whitelist add {player}")
        return f"`{player}`를 화이트리스트에 추가했습니다.\n" + discord_code_block(response)

    def _rcon_sync(self, command: str) -> str:
        try:
            with socket.create_connection(
                (self.settings.rcon_host, self.settings.rcon_port),
                timeout=self.settings.rcon_timeout_seconds,
            ) as sock:
                sock.settimeout(self.settings.rcon_timeout_seconds)
                send_rcon_packet(sock, 1, RCON_AUTH, self.settings.rcon_password)
                request_id, _, _ = read_rcon_packet(sock)
                if request_id == -1:
                    raise UserFacingError("RCON 로그인 실패: 비밀번호를 확인하세요.")

                send_rcon_packet(sock, 2, RCON_COMMAND, command)
                response_id, _, response = read_rcon_packet(sock)
                if response_id != 2:
                    raise ConnectionError(f"예상하지 못한 RCON 응답 ID입니다: {response_id}")
                return response
        except UserFacingError:
            raise
        except TimeoutError as exc:
            raise UserFacingError(f"RCON 응답 시간 초과({self.settings.rcon_timeout_seconds:g}초)") from exc
        except socket.timeout as exc:
            raise UserFacingError(f"RCON 응답 시간 초과({self.settings.rcon_timeout_seconds:g}초)") from exc
        except Exception as exc:
            raise UserFacingError(f"RCON 연결 실패: `{exc}`") from exc

    async def is_online(self) -> tuple[bool, str]:
        if not self.settings.rcon_password:
            return False, "RCON 비밀번호가 설정되지 않았습니다."

        try:
            response = await self.rcon("list")
            return True, response
        except UserFacingError as exc:
            return False, str(exc)

    async def start(self) -> str:
        online, response = await self.is_online()
        if online:
            return "이미 서버가 켜져 있습니다.\n" + discord_code_block(response)

        if not self.settings.minecraft_start_command:
            raise UserFacingError("`.env`에 `MINECRAFT_START_COMMAND`를 설정해야 서버를 켤 수 있습니다.")
        if not self.settings.minecraft_server_dir.exists():
            raise UserFacingError(f"서버 폴더가 없습니다: `{self.settings.minecraft_server_dir}`")

        self.settings.minecraft_log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = self.settings.minecraft_log_file.open("a", encoding="utf-8", errors="replace")

        creationflags = 0
        start_new_session = False
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            start_new_session = True

        try:
            process = subprocess.Popen(
                self.settings.minecraft_start_command,
                cwd=self.settings.minecraft_server_dir,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                shell=True,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except OSError as exc:
            log_handle.close()
            raise UserFacingError(f"서버 시작 실패: `{exc}`") from exc
        finally:
            try:
                log_handle.close()
            except OSError:
                pass

        for _ in range(max(1, self.settings.startup_check_seconds // 3)):
            await asyncio.sleep(3)
            online, response = await self.is_online()
            if online:
                return (
                    f"서버 시작 명령을 실행했고 RCON 연결도 확인했습니다. PID: `{process.pid}`\n"
                    + discord_code_block(response)
                )

        return (
            f"서버 시작 명령을 실행했습니다. PID: `{process.pid}`\n"
            f"아직 RCON 응답은 없습니다. 로그를 확인하세요: `{self.settings.minecraft_log_file}`"
        )

    async def stop(self) -> str:
        online, _ = await self.is_online()
        if not online:
            return "서버가 꺼져 있거나 RCON에 연결할 수 없습니다."

        response = await self.rcon("stop")
        for _ in range(max(1, self.settings.shutdown_check_seconds // 3)):
            await asyncio.sleep(3)
            online, _ = await self.is_online()
            if not online:
                return "서버 종료 명령을 보냈고 RCON 연결이 끊어진 것을 확인했습니다."

        return "서버 종료 명령을 보냈지만 아직 RCON이 응답합니다.\n" + discord_code_block(response)

    async def status(self) -> str:
        online, response = await self.is_online()
        if online:
            return "서버가 켜져 있습니다.\n" + discord_code_block(response)
        return "서버가 꺼져 있거나 RCON에 연결할 수 없습니다.\n" + discord_code_block(response)


def is_authorized(interaction: discord.Interaction, settings: Settings) -> bool:
    user_id = interaction.user.id
    if user_id in settings.allowed_user_ids:
        return True

    roles = getattr(interaction.user, "roles", [])
    if any(role.id in settings.allowed_role_ids for role in roles):
        return True

    permissions = getattr(interaction.user, "guild_permissions", None)
    if settings.allow_discord_admins and permissions and permissions.administrator:
        return True

    return False


async def run_interaction(
    interaction: discord.Interaction,
    settings: Settings,
    action,
) -> None:
    command = summarize_interaction_command(interaction)
    if not is_authorized(interaction, settings):
        log_command_event(interaction, "unauthorized", command)
        await interaction.response.send_message(
            "이 명령을 쓸 권한이 없습니다. `.env`의 허용 유저/역할 ID를 확인하세요.",
            ephemeral=True,
        )
        return

    log_command_event(interaction, "started", command)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        message = await action()
    except UserFacingError as exc:
        log_command_event(interaction, "failed", command, str(exc))
        message = f"실패: {exc}"
    except Exception:
        LOGGER.exception("Command crashed: command=%s user=%s user_id=%s", command, interaction.user, interaction.user.id)
        message = "예상치 못한 오류가 났습니다. 봇 콘솔 로그를 확인하세요."
    else:
        log_command_event(interaction, "completed", command)

    await interaction.followup.send(message[:1990], ephemeral=True)


def create_bot(settings: Settings) -> commands.Bot:
    controller = MinecraftController(settings)
    intents = discord.Intents.default()

    class LunaMinecraftBot(commands.Bot):
        async def setup_hook(self) -> None:
            guild = discord.Object(id=settings.discord_guild_id) if settings.discord_guild_id else None
            if guild:
                self.tree.add_command(mc_group, guild=guild)
                synced = await self.tree.sync(guild=guild)
                scope = f"guild {settings.discord_guild_id}"
            else:
                self.tree.add_command(mc_group)
                synced = await self.tree.sync()
                scope = "global"
            LOGGER.info("Synced %s application commands to %s.", len(synced), scope)

    bot = LunaMinecraftBot(command_prefix="!", intents=intents)
    mc_group = app_commands.Group(name="mc", description="Minecraft server controls")

    @mc_group.command(name="start", description="마인크래프트 서버를 켭니다.")
    async def start(interaction: discord.Interaction) -> None:
        await run_interaction(interaction, settings, controller.start)

    @mc_group.command(name="stop", description="RCON stop 명령으로 서버를 안전하게 끕니다.")
    async def stop(interaction: discord.Interaction) -> None:
        await run_interaction(interaction, settings, controller.stop)

    @mc_group.command(name="status", description="RCON으로 서버 상태를 확인합니다.")
    async def status(interaction: discord.Interaction) -> None:
        await run_interaction(interaction, settings, controller.status)

    @mc_group.command(name="rcon", description="마인크래프트 RCON 명령어를 실행합니다.")
    @app_commands.describe(command="예: list, say hello, whitelist add player")
    async def rcon(interaction: discord.Interaction, command: str) -> None:
        async def action() -> str:
            response = await controller.rcon(command)
            return f"실행: `{clean_command(command)}`\n" + discord_code_block(response)

        await run_interaction(interaction, settings, action)

    @mc_group.command(name="whitelist-add", description="플레이어를 화이트리스트에 추가합니다.")
    @app_commands.describe(player="추가할 Minecraft Java 닉네임")
    async def whitelist_add(interaction: discord.Interaction, player: str) -> None:
        await run_interaction(interaction, settings, lambda: controller.whitelist_add(player))

    @bot.event
    async def on_ready() -> None:
        LOGGER.info("Logged in as %s (%s).", bot.user, bot.user.id if bot.user else "unknown")

    return bot


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        settings = Settings.from_env()
    except UserFacingError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 2

    bot = create_bot(settings)
    bot.run(settings.discord_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
