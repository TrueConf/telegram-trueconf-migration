import os
import io
import sys
import logging
import asyncio
import ffmpeg
import orjson
import tomlkit
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Mapping
from zoneinfo import ZoneInfo
from collections import OrderedDict
from tqdm import tqdm
from colorama import Fore, Style
from trueconf import Bot, ParseMode
from trueconf.types import FSInputFile, BufferedInputFile
from trueconf.exceptions import ApiErrorException
from trueconf.types.responses import (
    CreateChannelResponse,
    CreateGroupChatResponse,
    CreateP2PChatResponse,
    SendFileResponse,
    SendMessageResponse
)

LOGGER = logging.getLogger("tg2tc")
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpx._transports").setLevel(logging.ERROR)

# for Windows
if os.name == "nt":
    msys_path = r"C:\msys64\mingw64\bin"
    if os.path.exists(msys_path):
        os.add_dll_directory(msys_path)
        os.environ["PATH"] = msys_path + os.pathsep + os.environ.get("PATH", "")

from lottie.parsers.tgs import parse_tgs
from lottie.exporters.gif import export_webp
from PIL import features

if not hasattr(features, "webp_anim"):
    features.webp_anim = features.check("webp")

import lottie.parsers.svg.builder as lottie_builder


def safe_trim_offlocal(self, t, local_start, local_length, total_length):
    if local_length == 0:
        return 0
    return (t * total_length - local_start) / local_length

lottie_builder.SvgBuilder._trim_offlocal = safe_trim_offlocal


def get_work_dir() -> Path:
    if sys.platform.startswith("win"):
        localappdata = os.getenv("LOCALAPPDATA")
        base_dir = (
            Path(localappdata) if localappdata else Path.home() / "AppData" / "Local"
        )
        return base_dir / "TrueConf" / "tg2tc"
    return Path.home() / ".tg2tc"


MAX_ACTIVE_CONNECTIONS = 128
config: Mapping[str, Any] = {}
telegram_export_dir = Path()
data = {}
IS_DATATIME = False
IS_TGS_STICKER = False
CAPTION = ""
TIMEZONE = timezone.utc
IS_CONVERT_VOICE = False
COVER_PATH = None
topic_template = ""
CHAT_NAME = None
TOPICS_IDS = {}
MSG_MAP = {}
memo = {}

PROGRESS_CALLBACK = None
LOG_CALLBACK = None
SHOULD_CANCEL = None
IS_INTERACTIVE = (
    bool(getattr(sys.stdout, "isatty", lambda: False)())
    if sys.stdout is not None
    else False
)


def emit_progress(current: int, total: int):
    if callable(PROGRESS_CALLBACK):
        PROGRESS_CALLBACK(current, total)
        return
    if not IS_INTERACTIVE:
        print(f"PROGRESS_MESSAGE::{current}::{total}", flush=True)


def emit_error_message(text: str):
    if callable(LOG_CALLBACK):
        LOG_CALLBACK(str(text))
        return
    if not IS_INTERACTIVE:
        print(f"ERROR_MESSAGE::{text}", flush=True)

def emit_log_message(text: str):
    if callable(LOG_CALLBACK):
        LOG_CALLBACK(str(text))
        return
    if not IS_INTERACTIVE:
        print(str(text), flush=True)

def emit_result(payload: dict):
    if not IS_INTERACTIVE:
        print("TRANSFER_RESULT::" + orjson.dumps(payload).decode("utf-8"), flush=True)


# Support for cancellation from GUI or in-process
def check_canceled():
    if callable(SHOULD_CANCEL) and SHOULD_CANCEL():
        raise RuntimeError("CHAT_TRANSFER_CANCELED")


class FileNotIncluded(Exception):
    pass

def load_context(
    config_path: str = "config.toml",
    progress_callback=None,
    log_callback=None,
    should_cancel=None,
):
    global config
    global telegram_export_dir
    global data
    global IS_DATATIME
    global IS_TGS_STICKER
    global CAPTION
    global TIMEZONE
    global IS_CONVERT_VOICE
    global COVER_PATH
    global topic_template
    global CHAT_NAME
    global TOPICS_IDS
    global MSG_MAP
    global memo
    global PROGRESS_CALLBACK
    global LOG_CALLBACK
    global SHOULD_CANCEL
    PROGRESS_CALLBACK = progress_callback
    LOG_CALLBACK = log_callback
    SHOULD_CANCEL = should_cancel

    LOGGER.info(f"Opening config file: {config_path}")
    LOGGER.info(f"Config file absolute path: {Path(config_path).absolute()}")
    LOGGER.info(f"Current working directory: {Path.cwd()}")
    LOGGER.info(f"Config file exists: {Path(config_path).exists()}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = tomlkit.load(f)
        text = f"Read {Path(config_path).name}"
        if IS_INTERACTIVE:
            print(f"{Fore.BLUE}{text}{Style.RESET_ALL}")
        emit_log_message(text)

    telegram_export_dir = Path(config["telegram_export_dir"])

    if telegram_export_dir.exists():
        with open(telegram_export_dir / "result.json", "rb") as f:
            data = orjson.loads(f.read())
            text = "Read result.json"
            if IS_INTERACTIVE:
                print(f"{Fore.BLUE}{text}{Style.RESET_ALL}")
            emit_log_message(text)
        check_canceled()
    else:
        raise FileNotFoundError(
            f"Invalid Path to Telegram Export Dir: '{telegram_export_dir}'"
        )

    (get_work_dir() / "videos").mkdir(parents=True, exist_ok=True)

    IS_DATATIME = config["chat"].get("datetime", False).get("view_original_time_in_message", False)
    IS_TGS_STICKER = config["chat"].get("stickers", False).get("convert_telegram_stickers_to_webp", False)
    CAPTION = config["chat"].get("datetime", "").get("caption", "")
    timezone_value = config["chat"].get("datetime", False).get("timezone", False)
    TIMEZONE = ZoneInfo(timezone_value) if timezone_value else timezone.utc
    IS_CONVERT_VOICE = config["chat"].get("voice_message", False).get("convert_voice_message_to_video", False)
    COVER_PATH = config["chat"].get("voice_message", "").get("cover_image")
    topic_template = config["chat"].get("supergroup_topic_name_template", False)
    CHAT_NAME = config["chat"].get("name", None)

    TOPICS_IDS = {
        m['id']: {
            "title": topic_template.format(topic=m.get("title"), supergroup=CHAT_NAME),
            "trueconf_chat_id": None
        }
        for m in tqdm(data["messages"], desc="Search topics", disable=not IS_INTERACTIVE)
        if m.get('type') == 'service' and m.get('action') == 'topic_created'
    }
    TOPICS_IDS[1] = {
        "title": f"# {CHAT_NAME}",
        "trueconf_chat_id": None
    }

    MSG_MAP = {m['id']: m for m in tqdm(data["messages"], desc="Build messages map", disable=not IS_INTERACTIVE)}
    memo = {}

def resolve_chat_owner(config: Mapping[str, Any]) -> str | None:
    owner_value = str(config.get("chat", {}).get("owner", "")).strip()
    if not owner_value:
        return None

    users = config.get("users", {}) or {}

    if owner_value in users:
        return owner_value

    owner_normalized = owner_value.lstrip("@").lower().replace("/", "\\")

    for user_key, user_data in users.items():
        trueconf_id = (
            str(user_data.get("trueconf_id", "")).strip().lower().replace("/", "\\")
        )
        username = str(user_data.get("username", "")).strip().lstrip("@").lower()
        telegram_id = str(user_data.get("telegram_id", "")).strip()

        if owner_normalized and owner_normalized == trueconf_id:
            return user_key
        if owner_normalized and username and owner_normalized == username:
            return user_key
        if owner_value == telegram_id:
            return user_key

    return None


def build_content_from_text_entities(text_entities: List[Dict[str, str]], timestamp, forwarded_from) -> Optional[str]:
    result_in_html = ""

    if forwarded_from:

        result_in_html = f"<b><i>Переслано от {forwarded_from}:</i></b>\n\n"

    for entiti in text_entities:

        match entiti["type"]:

            case "plain":
                result_in_html += entiti["text"]
            case "bold":
                result_in_html += f"<b>{entiti["text"]}</b>"
            case "italic":
                result_in_html += f"<i>{entiti["text"]}</i>"
            case "strikethrough":
                result_in_html += f"<s>{entiti["text"]}</s>"
            case "underline":
                result_in_html += f"<u>{entiti["text"]}</u>"
            case "code":
                if len(entiti["text"].strip()) > 0:
                    result_in_html += f"<b>Моноширинный текст:</b>\n\n<i>{entiti["text"]}</i>"
            case "pre":
                result_in_html += f"<b>Код {entiti['language'].capitalize()}:</b>\n\n<i>{entiti["text"]}</i>"
            case "text_link":
                result_in_html += f"<a href='{entiti["href"]}'>{entiti["text"]}</a>"
            case "link":
                result_in_html += f"{entiti["text"]}"
            case "spoiler":
                result_in_html += f"[{entiti["text"]}]"
            case "blockquote":
                result_in_html += f"<b>Цитата:</b>\n\n<i>{entiti["text"]}</i>"
            case _:
                result_in_html += entiti["text"]

    if IS_DATATIME:
        timestamp = int(timestamp)
        dt = datetime.fromtimestamp(timestamp, tz=TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %z")
        result_in_html = f"{result_in_html}\n\n<i>{CAPTION}{dt}</i>"

    return result_in_html


async def create_chat_and_add_users():
    check_canceled()
    owner = resolve_chat_owner(config)
    try:
        owner_user = config["users"][owner]
        token = config["users"][owner].get("access_token", False)
    except KeyError:
        print(f"{Fore.RED}ERROR! Param 'chat.owner' is bad or empty. Check config.toml{Style.RESET_ALL}")
        sys.exit(1)
    verify_ssl = config["server"].get("verify_ssl", False)
    address = config["server"]["address"]
    web_port = config["server"].get("web_port", 443)

    if not token:
        password = owner_user.get("password", False)
        trueconf_id = owner_user.get("trueconf_id", False)
        if not password:
            raise ValueError("Password or access token is required")
        if not trueconf_id:
            raise ValueError("Owner trueconf_id is required")

        bot = Bot.from_credentials(
            server=address,
            username=trueconf_id,
            password=password,
            verify_ssl=verify_ssl,
            web_port=web_port,

        )
    else:
        bot = Bot(server=address, token=token, verify_ssl=verify_ssl, web_port=web_port)

    await bot.start()
    await bot.connected_event.wait()
    await bot.authorized_event.wait()

    async def add_user_to_chat(chat_id, chat_name):
        added_trueconf_ids = set()
        for user in config["users"].values():
            check_canceled()
            trueconf_id = str(user.get("trueconf_id", "")).strip()
            if not trueconf_id:
                continue
            if trueconf_id in added_trueconf_ids:
                continue

            added_trueconf_ids.add(trueconf_id)
            try:
                await bot.add_participant_to_chat(
                    chat_id=chat_id,
                    user_id=trueconf_id
                )
            except Exception as e:
                error_text = str(e)
                if "[309] User already in chat" in error_text:
                    continue
                if IS_INTERACTIVE:
                    print("Error:", e)
                emit_error_message(f"Не удалось добавить пользователя в чат: {trueconf_id}. {error_text}")
        text = f"Users have been added to '{chat_name}'"
        if IS_INTERACTIVE:
            print(f"{Fore.GREEN}{text}{Style.RESET_ALL}")
        emit_log_message(text)

    created_chat_id = None

    try:
        match config["chat"].get("type", False):
            case "supergroup":
                for topic_id, info in TOPICS_IDS.items():
                    created_instance: CreateGroupChatResponse = await bot.create_group_chat(title=info['title'])
                    info['trueconf_chat_id'] = created_instance.chat_id
                    prefix = "SUPERGROUP" if topic_id == 1 else "TOPIC"
                    text = f"[{prefix}] '{info['title']}' -> ID: {info['trueconf_chat_id']}"
                    if IS_INTERACTIVE:
                        print(f"{Fore.GREEN}{text} {Style.RESET_ALL}")
                    emit_log_message(text)
                    await add_user_to_chat(chat_id=created_instance.chat_id, chat_name=info['title'])
            case "channel":
                created_instance: CreateChannelResponse = await bot.create_channel(title=CHAT_NAME)
                text = f"Created '{CHAT_NAME}' channel"
                if IS_INTERACTIVE:
                    print(f"{Fore.GREEN}{text} {Style.RESET_ALL}")
                emit_log_message(text)
                await add_user_to_chat(chat_id=created_instance.chat_id, chat_name=CHAT_NAME)
                created_chat_id = created_instance.chat_id
            case "group":
                created_instance: CreateGroupChatResponse = await bot.create_group_chat(title=CHAT_NAME)
                text = f"Created '{CHAT_NAME}' group chat"
                if IS_INTERACTIVE:
                    print(f"{Fore.GREEN}{text} {Style.RESET_ALL}")
                emit_log_message(text)
                await add_user_to_chat(chat_id=created_instance.chat_id, chat_name=CHAT_NAME)
                created_chat_id = created_instance.chat_id
            case "personal":
                users = list(config["users"].keys())
                user_id = users[1] if users[0] == owner else users[0]
                created_instance: CreateP2PChatResponse = await bot.create_personal_chat(user_id=user_id)
                text = f"Created personal chat with {user_id}"
                if IS_INTERACTIVE:
                    print(f"{Fore.GREEN}{text} {Style.RESET_ALL}")
                emit_log_message(text)
                created_chat_id = created_instance.chat_id
            case _:
                print("erre")
    finally:
        try:
            await bot.shutdown()
        except Exception as shutdown_error:
            emit_error_message(f"Bot shutdown warning: {shutdown_error}")
    return created_chat_id


def make_from_id_key(user_data: Dict[str, Any]) -> str:
    if user_data.get("type", False) == "user":
        return f"user{user_data['telegram_id']}"
    return f"channel{user_data['telegram_id']}"


def build_user_configs() -> Dict[str, Dict[str, Any]]:
    user_configs: Dict[str, Dict[str, Any]] = {}
    for _, data_ in config["users"].items():
        telegram_id = str(data_.get("telegram_id", "")).strip()
        if not telegram_id:
            continue

        user_configs[f"user{telegram_id}"] = data_
        user_configs[f"channel{telegram_id}"] = data_
    return user_configs


async def create_bot_from_user_data(data_: Dict[str, Any]) -> Bot:
    verify_ssl = config["server"].get("verify_ssl", False)
    address = config["server"]["address"]
    web_port = config["server"].get("web_port", 443)

    token = data_.get("access_token", False)
    if not token:
        password = data_.get("password", False)
        trueconf_id = data_.get("trueconf_id", False)
        if not password:
            raise ValueError("Password or access token is required")
        bot = Bot.from_credentials(
            server=address,
            username=trueconf_id,
            password=password,
            verify_ssl=verify_ssl,
            web_port=web_port,
        )
    else:
        bot = Bot(server=address, token=token, verify_ssl=verify_ssl, web_port=web_port)

    await bot.start()
    await bot.connected_event.wait()
    await bot.authorized_event.wait()
    return bot


async def get_bot_for_user(
    from_id: str,
    active_users: "OrderedDict[str, Bot]",
    user_configs: Dict[str, Dict[str, Any]],
) -> Bot:
    if from_id in active_users:
        bot = active_users[from_id]
        active_users.move_to_end(from_id)
        return bot

    user_data = user_configs.get(from_id)
    if user_data is None:
        raise KeyError(from_id)

    if len(active_users) >= MAX_ACTIVE_CONNECTIONS:
        old_from_id, old_bot = active_users.popitem(last=False)
        print(
            f"{Fore.YELLOW}Connection pool limit reached ({MAX_ACTIVE_CONNECTIONS}). "
            f"Shutdown oldest bot: {old_from_id}{Style.RESET_ALL}"
        )
        try:
            await old_bot.shutdown()
        except Exception as e:
            print(
                f"{Fore.RED}Error during shutdown of '{old_from_id}': {e}{Style.RESET_ALL}"
            )

    bot = await create_bot_from_user_data(user_data)
    active_users[from_id] = bot
    return bot


async def convert_voice_message_to_video(audio_file: Path, date):
    print(f"{Fore.BLUE}Converting voice message to video...{Style.RESET_ALL}")
    audio_path = Path(audio_file).expanduser().resolve(strict=False)

    cover_path = Path(COVER_PATH).expanduser()
    if not cover_path.is_absolute():
        candidate = telegram_export_dir / cover_path
        cover_path = candidate if candidate.exists() else cover_path
    cover_path = cover_path.resolve(strict=False)

    output_dir = get_work_dir() / "videos"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (output_dir / audio_path.stem).with_suffix(".mp4")
    print(output_path)
    date = datetime.fromisoformat(date)
    timestamp = date.strftime("%Y-%m-%d %H:%M:%S")

    video_stream = (
        ffmpeg.input(str(cover_path), loop=1)  # -loop 1
        .filter("scale", 1920, 1080)  # 720p (растянет до 16:9)
        .drawtext(
            text=f"Telegram\n{timestamp}",
            fontcolor="white",
            fontsize=18,
            x="w-tw-20",
            y="h-th-20",
            box=1,
            boxcolor="black@0.5",
            boxborderw=5
        )
    )

    audio_stream = ffmpeg.input(str(audio_file))

    (
        ffmpeg
        .output(
            video_stream,
            audio_stream,
            str(output_path),
            vcodec="libx264",
            acodec="libmp3lame",
            pix_fmt="yuv420p",
            shortest=None
        )
        .overwrite_output()
        .run()
    )

    return output_path


def get_topic_id_iterative(start_msg_id, msg_map, topics_dict):
    curr_id = start_msg_id
    path = []

    while curr_id not in memo:
        if curr_id in topics_dict:
            memo[curr_id] = curr_id
            break

        msg = msg_map.get(curr_id)

        if not msg or 'reply_to_message_id' not in msg:
            memo[curr_id] = 1
            break

        path.append(curr_id)
        curr_id = msg['reply_to_message_id']

    root_topic_id = memo[curr_id]

    for msg_id in path:
        memo[msg_id] = root_topic_id

    return root_topic_id


async def fill_chat(chat_id, convert_voice_message):
    check_canceled()
    map_message_ids = {}
    active_users: "OrderedDict[str, Bot]" = OrderedDict()
    user_configs = build_user_configs()

    def get_message_id(reply_id):

        ids = map_message_ids.get(reply_id, [])

        if len(ids) == 1:
            return ids[0]
        elif len(ids) == 2:
            return ids[1]
        return None

    def check_file(file: str):
        if "File not included" in file:
            raise FileNotIncluded("File not included. Change data exporting settings to download.")
        else:
            return file
    total_messages = len(data["messages"])
    emit_progress(0, total_messages)
    for count, message in enumerate(tqdm(data["messages"], disable=not IS_INTERACTIVE)):
        check_canceled()
        map_message_ids[message["id"]] = []
        file = message.get("file", "")
        text, message_id = None, None

        if config["chat"]["type"] == "supergroup":
            topic_id = get_topic_id_iterative(message['id'], MSG_MAP, TOPICS_IDS)
            chat_id = TOPICS_IDS[topic_id]["trueconf_chat_id"]

        if message.get("text_entities", []) or message.get("forwarded_from", ""):
            text = build_content_from_text_entities(message["text_entities"], message["date_unixtime"], message.get("forwarded_from", ""))


        if message.get("reply_to_message_id", False):
            message_id = get_message_id(message["reply_to_message_id"])

        from_id = message.get("from_id", False)

        if from_id is False:
            continue

        try:
            bot = await get_bot_for_user(
                from_id=from_id,
                active_users=active_users,
                user_configs=user_configs,
            )

            if message.get("photo", False):
                r: SendFileResponse = await bot.send_photo(
                    chat_id=chat_id,
                    file=FSInputFile(path=telegram_export_dir / message["photo"]),
                    preview=FSInputFile(path=telegram_export_dir / message["photo"]),
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_message_id=message_id
                )
                map_message_ids[message["id"]].append(r.message_id)

            elif message.get("media_type", False):
                if Path(file).is_file():
                    continue
                match message["media_type"]:
                    case "voice_message":
                        audio_file = telegram_export_dir / check_file(file)
                        if convert_voice_message:
                            audio_file = await convert_voice_message_to_video(
                                audio_file=audio_file,
                                date=message["date"],
                            )
                        r: SendFileResponse = await bot.send_document(
                            chat_id=chat_id, file=FSInputFile(path=audio_file))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "animation":
                        r: SendFileResponse = await bot.send_document(
                            chat_id=chat_id, file=FSInputFile(path=telegram_export_dir / check_file(file)))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "video_message":
                        r: SendFileResponse = await bot.send_document(
                            chat_id=chat_id, file=FSInputFile(path=telegram_export_dir / check_file(file)))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "video_file":
                        r: SendFileResponse = await bot.send_document(
                            chat_id=chat_id,
                            file=FSInputFile(path=telegram_export_dir / check_file(file)),
                            caption=text,
                            parse_mode=ParseMode.HTML,
                            reply_message_id=message_id
                        )
                        map_message_ids[message["id"]].append(r.message_id)

                    case "sticker" if message["mime_type"] == "video/webm":
                        r: SendFileResponse = await bot.send_document(
                            chat_id=chat_id,
                            file=FSInputFile(path=telegram_export_dir / check_file(file)),
                            reply_message_id=message_id
                        )
                        map_message_ids[message["id"]].append(r.message_id)

                    case "sticker" if message["mime_type"] == "image/webp":
                        r: SendFileResponse = await bot.send_sticker(
                            chat_id=chat_id,
                            file=FSInputFile(path=telegram_export_dir / check_file(file)),
                            reply_message_id=message_id
                        )
                        map_message_ids[message["id"]].append(r.message_id)

                    case "sticker" if message["mime_type"] == "application/x-tgsticker":
                        if IS_TGS_STICKER:
                            animation = parse_tgs(str(telegram_export_dir / check_file(file)))
                            buf = io.BytesIO()
                            export_webp(
                                animation,
                                buf,
                                quality=50,
                                skip_frames=4
                            )
                            buf.seek(0)
                            r: SendFileResponse = await bot.send_sticker(
                                chat_id=chat_id,
                                file=BufferedInputFile(
                                    file=buf.getvalue(),
                                    filename="AnimatedSticker.webp",
                                    mimetype="image/webp",
                                    file_size=len(buf.getbuffer())
                                ),
                                reply_message_id=message_id
                            )
                        else:
                            r: SendMessageResponse = await bot.send_message(
                                chat_id=chat_id,
                                text=message["sticker_emoji"],
                                parse_mode=ParseMode.TEXT,
                                reply_message_id=message_id
                            )

                        map_message_ids[message["id"]].append(r.message_id)

            elif message.get("file", False):
                r: SendFileResponse = await bot.send_document(
                    chat_id=chat_id,
                    file=FSInputFile(path=telegram_export_dir / file),
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_message_id=message_id
                )
                map_message_ids[message["id"]].append(r.message_id)

            else:
                r: SendMessageResponse = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_message_id=message_id
                )
                map_message_ids[message["id"]].append(r.message_id)

        except KeyError:
            try:
                text = f"[item: #{count}, id: {message.get('id')}]: Skipped message from '{message['from_id']}', because this ID was not added to config.toml."
                if IS_INTERACTIVE:
                    print(f"{Fore.YELLOW}{text}{Style.RESET_ALL}")
                emit_log_message(text)
            except KeyError:
                text = f"[item: #{count}, id: {message.get('id')}]: Invalid from_id parameter in result.json: {message}"
                if IS_INTERACTIVE:
                    print(f"{Fore.RED}{text}{Style.RESET_ALL}")
                emit_error_message(text)
        except (FileNotIncluded, FileNotFoundError) as e:
            text = f"[item: #{count}, id: {message.get('id')}]: Skipped message '{message['id']}'. {e}"
            if IS_INTERACTIVE:
                print(f"{Fore.YELLOW}{text}{Style.RESET_ALL}")
            emit_log_message(text)
        except ApiErrorException as e:
            if IS_INTERACTIVE:
                print(e)
            emit_error_message(f"API error: {e}")
            break
        emit_progress(count + 1, total_messages)
    else:
        text = "Chat transfer complete"
        if IS_INTERACTIVE:
            print(f"{Fore.GREEN}✅ {text}{Style.RESET_ALL}")
        emit_log_message(text)

    try:
        for name, bot in active_users.items():
            await bot.shutdown()
    except Exception as shutdown_error:
        emit_error_message(f"Pool shutdown warning: {shutdown_error}")
    shutdown_text = "Bots are shut down"
    if IS_INTERACTIVE:
        print(f"{Fore.BLUE}{shutdown_text}{Style.RESET_ALL}")
    emit_log_message(shutdown_text)

def run_chat_transfer(
    config_path: str = "config.toml",
    progress_callback=None,
    log_callback=None,
    should_cancel=None,
) -> dict:
    return asyncio.run(
        main(
            config_path,
            progress_callback=progress_callback,
            log_callback=log_callback,
            should_cancel=should_cancel,
        )
    )

async def main(
    config_path: str = "config.toml",
    progress_callback=None,
    log_callback=None,
    should_cancel=None,
) -> dict:
    emit_log_message("Этап 1/3: чтение конфигурации и экспорта Telegram...")
    load_context(
        config_path,
        progress_callback=progress_callback,
        log_callback=log_callback,
        should_cancel=should_cancel,
    )

    check_canceled()
    emit_log_message("Этап 2/3: создание чата и добавление пользователей...")
    chat_id = await create_chat_and_add_users()
    check_canceled()
    emit_log_message("Этап 3/3: перенос сообщений...")
    await fill_chat(chat_id=chat_id, convert_voice_message=IS_CONVERT_VOICE)

    result = {
        "status": "ok",
        "chat_name": CHAT_NAME,
        "chat_type": config["chat"].get("type", ""),
        "chat_id": chat_id,
    }
    emit_result(result)
    return result



if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.toml"
    run_chat_transfer(config_path)
