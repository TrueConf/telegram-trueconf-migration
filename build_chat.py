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
from typing import List, Optional, Dict
from zoneinfo import ZoneInfo
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

#for Windows
if os.name == 'nt':
    msys_path = r"C:\msys64\mingw64\bin"
    if os.path.exists(msys_path):
        os.add_dll_directory(msys_path)
        os.environ['PATH'] = msys_path + os.pathsep + os.environ.get('PATH', '')

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


os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    filename="logs/bot.log",
    encoding="utf-8",
)


class FileNotIncluded(Exception):
    pass


with open("config2.toml", "r", encoding="utf-8") as f:
    config = tomlkit.load(f)
    print(f"{Fore.BLUE}Read config.toml{Style.RESET_ALL}")

telegram_export_dir = Path(config["telegram_export_dir"])

if telegram_export_dir.exists():
    with open(telegram_export_dir / "result.json", "rb") as f:
        data = orjson.loads(f.read())
        print(f"{Fore.BLUE}Read result.json{Style.RESET_ALL}")
else:
    print(
        f"{Fore.RED}ERROR! Invalid Path to Telegram Export Dir:{Style.RESET_ALL} "
        f"{Fore.GREEN}'{telegram_export_dir}'{Style.RESET_ALL}"
    )
    sys.exit()

Path("videos").mkdir(parents=True, exist_ok=True)

# Consts section
IS_DATATIME = config["chat"].get("datetime", False).get("view_original_time_in_message", False)
IS_TGS_STICKER = config["chat"].get("stikers", False).get("convert_telegram_stikers_to_webp", False)
CAPTION = config["chat"].get("datetime", "").get("caption", "")
TIMEZONE = config["chat"].get("datetime", False).get("timezone", False)
TIMEZONE = ZoneInfo(TIMEZONE) if TIMEZONE else timezone.utc
IS_CONVERT_VOICE = config["chat"].get("voice_message", False).get("convert_voice_message_to_video", False)
COVER_PATH = config["chat"].get("voice_message", "").get("cover_image")
topic_template: str = config["chat"].get("supergroup_topic_name_template", False)
CHAT_NAME = config["chat"].get("name", None)
TOPICS_IDS = {
    m['id']: {
        "title": topic_template.format(topic=m.get("title"), supergroup=CHAT_NAME),
        "trueconf_chat_id": None
    }
    for m in tqdm(data["messages"], desc="Search topics")
    if m.get('type') == 'service' and m.get('action') == 'topic_created'
}
TOPICS_IDS[1] = {
    "title": f"# {CHAT_NAME}",
    "trueconf_chat_id": None}
MSG_MAP = {m['id']: m for m in tqdm(data["messages"], desc="Build messages map")}
memo = {}


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
    owner = config["chat"].get("owner", None)
    try:
        token = config["users"][owner].get("access_token", False)
    except KeyError:
        print(f"{Fore.RED}ERROR! Param 'chat.owner' is bad or empty. Check config.toml{Style.RESET_ALL}")
        sys.exit(1)
    verify_ssl = config["server"].get("verify_ssl", False)
    address = config["server"]["address"]
    web_port = config["server"].get("web_port", 443)

    if not token:
        password = config["users"][owner].get("password", False)
        if not password:
            raise ValueError("Password or access token is required")

        bot = Bot.from_credentials(
            server=address,
            username=owner,
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
        for user in config["users"].values():
            try:
                await bot.add_participant_to_chat(
                    chat_id=chat_id,
                    user_id=user["trueconf_id"]
                )
            except Exception as e:

                print("Error:", e)
        print(f"{Fore.GREEN}Users have been added to '{chat_name}'{Style.RESET_ALL}")

    match config["chat"].get("type", False):
        case "supergroup":
            for topic_id, info in TOPICS_IDS.items():
                created_instance: CreateGroupChatResponse = await bot.create_group_chat(title=info['title'])
                info['trueconf_chat_id'] = created_instance.chat_id
                prefix = "SUPERGROUP" if topic_id == 1 else "TOPIC"
                print(f"[{prefix}] '{info['title']}' -> ID: {info['trueconf_chat_id']}")
                await add_user_to_chat(chat_id=created_instance.chat_id, chat_name=info['title'])
        case "channel":
            created_instance: CreateChannelResponse = await bot.create_channel(title=CHAT_NAME)
            print(f"{Fore.GREEN}Created '{CHAT_NAME}' channel {Style.RESET_ALL}")
            await add_user_to_chat(chat_id=created_instance.chat_id, chat_name=CHAT_NAME)
            return created_instance.chat_id
        case "group":
            created_instance: CreateGroupChatResponse = await bot.create_group_chat(title=CHAT_NAME)
            print(f"{Fore.GREEN}Created '{CHAT_NAME}' group chat {Style.RESET_ALL}")
            await add_user_to_chat(chat_id=created_instance.chat_id, chat_name=CHAT_NAME)
            return created_instance.chat_id
        case "personal":
            users = list(config["users"].keys())
            user_id = users[1] if users[0] == owner else users[0]
            created_instance: CreateP2PChatResponse = await bot.create_personal_chat(user_id=user_id)
            print(f"{Fore.GREEN}Created personal chat with {user_id} {Style.RESET_ALL}")
            return created_instance.chat_id
        case _:
            print("erre")
    return None


async def convert_voice_message_to_video(audio_file: Path, date):
    print(f"{Fore.BLUE}Converting voice message to video...{Style.RESET_ALL}")
    audio_path = Path(audio_file).expanduser().resolve(strict=False)

    cover_path = Path(COVER_PATH).expanduser()
    if not cover_path.is_absolute():
        candidate = (telegram_export_dir / cover_path)
        cover_path = candidate if candidate.exists() else cover_path
    cover_path = cover_path.resolve(strict=False)

    output_dir = Path("videos")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (output_dir / audio_path.stem).with_suffix(".mp4")
    print(output_path)
    date = datetime.fromisoformat(date)
    timestamp = date.strftime("%Y-%m-%d %H:%M:%S")

    video_stream = (
        ffmpeg
        .input(str(cover_path), loop=1)  # -loop 1
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
        # Проверяем, является ли текущий ID зарегистрированным топиком
        if curr_id in topics_dict:
            memo[curr_id] = curr_id
            break

        msg = msg_map.get(curr_id)

        # Если сообщения нет в базе или оно — корень без родителя
        if not msg or 'reply_to_message_id' not in msg:
            # Считаем, что это относится к основному чату (ID 1)
            memo[curr_id] = 1
            break

        # Идем вверх по цепочке
        path.append(curr_id)
        curr_id = msg['reply_to_message_id']

    # Вытаскиваем финальный ID топика из кеша
    root_topic_id = memo[curr_id]

    # Прописываем этот топик всей пройденной цепочке (Path Compression)
    for msg_id in path:
        memo[msg_id] = root_topic_id

    return root_topic_id


async def fill_chat(chat_id, convert_voice_message):
    map_message_ids = {}
    users_object = {}

    verify_ssl = config["server"].get("verify_ssl", False)
    address = config["server"]["address"]
    web_port = config["server"].get("web_port", 443)

    for _, data_ in config["users"].items():
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

        if data_.get("type", False) == "user":
            users_object.update({f"user{data_['telegram_id']}": bot})
        else:
            users_object.update({f"channel{data_['telegram_id']}": bot})

    for bot in users_object.values():
        await bot.start()
        await bot.connected_event.wait()
        await bot.authorized_event.wait()

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
    for count, message in enumerate(data["messages"]):
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
            if message.get("photo", False):
                r: SendFileResponse = await users_object[from_id].send_photo(
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
                        if convert_voice_message:
                            audio_file_path = await convert_voice_message_to_video(
                                audio_file=telegram_export_dir / check_file(file),
                                date=message["date"],
                            )
                            r: SendFileResponse = await users_object[from_id].send_document(
                                chat_id=chat_id, file=FSInputFile(path=audio_file_path))
                            map_message_ids[message["id"]].append(r.message_id)

                    case "animation":
                        r: SendFileResponse = await users_object[from_id].send_document(
                            chat_id=chat_id, file=FSInputFile(path=telegram_export_dir / check_file(file)))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "video_message":
                        r: SendFileResponse = await users_object[from_id].send_document(
                            chat_id=chat_id, file=FSInputFile(path=telegram_export_dir / check_file(file)))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "video_file":
                        r: SendFileResponse = await users_object[from_id].send_document(
                            chat_id=chat_id,
                            file=FSInputFile(path=telegram_export_dir / check_file(file)),
                            caption=text,
                            parse_mode=ParseMode.HTML,
                            reply_message_id=message_id
                        )
                        map_message_ids[message["id"]].append(r.message_id)

                    case "sticker" if message["mime_type"] == "video/webm":
                        r: SendFileResponse = await users_object[from_id].send_document(
                            chat_id=chat_id,
                            file=FSInputFile(path=telegram_export_dir / check_file(file)),
                            reply_message_id=message_id
                        )
                        map_message_ids[message["id"]].append(r.message_id)

                    case "sticker" if message["mime_type"] == "image/webp":
                        r: SendFileResponse = await users_object[from_id].send_sticker(
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
                            r: SendFileResponse = await users_object[message["from_id"]].send_sticker(
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
                            r: SendMessageResponse = await users_object[message["from_id"]].send_message(
                                chat_id=chat_id,
                                text=message["sticker_emoji"],
                                parse_mode=ParseMode.TEXT,
                                reply_message_id=message_id
                            )

                        map_message_ids[message["id"]].append(r.message_id)

            elif message.get("file", False):
                r: SendFileResponse = await users_object[from_id].send_document(
                    chat_id=chat_id,
                    file=FSInputFile(path=telegram_export_dir / file),
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_message_id=message_id
                )
                map_message_ids[message["id"]].append(r.message_id)

            else:
                r: SendMessageResponse = await users_object[from_id].send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_message_id=message_id
                )
                map_message_ids[message["id"]].append(r.message_id)

        except KeyError:
            try:
                print(
                    f"[item: #{count}, id: {message.get('id')}]: {Fore.YELLOW}Skipped message from '{message['from_id']}', because this ID was not added to config.toml.{Style.RESET_ALL}")
            except KeyError:
                print(
                    f"[item: #{count}, id: {message.get('id')}]: {Fore.RED}Invalid from_id parameter in result.json:\n{Fore.BLUE}{message}{Style.RESET_ALL}\n")
        except (FileNotIncluded, FileNotFoundError) as e:
            print(f"[item: #{count}, id: {message.get('id')}]: {Fore.YELLOW}Skipped message '{message['id']}'.", e, f"{Style.RESET_ALL}")
        except ApiErrorException as e:
            print(e)
            break
    else:
        print(f"{Fore.GREEN}✅ Chat transfer complete{Style.RESET_ALL}")

    print(f"{Fore.BLUE}Bots are shut down{Style.RESET_ALL}")
    for name, bot in users_object.items():
        await bot.shutdown()


async def main() -> None:

    chat_id = await create_chat_and_add_users()
    await fill_chat(chat_id=chat_id, convert_voice_message=IS_CONVERT_VOICE)



if __name__ == "__main__":
    asyncio.run(main())
