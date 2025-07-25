import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict
from zoneinfo import ZoneInfo

import ffmpeg
import orjson
import tomlkit
from colorama import Fore, Style
from trueconf import Bot, ParseMode
from trueconf.types.responses import (
    CreateChannelResponse,
    CreateGroupChatResponse,
    CreateP2PChatResponse,
    SendFileResponse,
    SendMessageResponse
)

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    filename="logs/bot.log",
    encoding="utf-8",
)


class FileNotIncluded(Exception):
    pass


with open("config.toml", "rb") as f:
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
CAPTION = config["chat"].get("datetime", "").get("caption", "")
TIMEZONE = config["chat"].get("datetime", False).get("timezone", False)
TIMEZONE = ZoneInfo(TIMEZONE) if TIMEZONE else timezone.utc
IS_CONVERT_VOICE = config["chat"].get("voice_message", False).get("convert_voice_message_to_video", False)
COVER_PATH = config["chat"].get("voice_message", "").get("cover_image")


def build_content_from_text_entities(text_entities: List[Dict[str, str]], timestamp) -> Optional[str]:
    result_in_html = ""

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
    chat_name = config["chat"]["name"]
    owner = config["chat"].get("owner")
    try:
        token = config["users"][owner].get("access_token", False)
    except KeyError:
        print(f"{Fore.RED}ERROR! Param 'chat.owner' is bad or empty. Check config.toml{Style.RESET_ALL}")
        sys.exit(1)
    verify_ssl = config["server"].get("verify_ssl", False)
    address = config["server"]["address"]
    if not token:
        password = config["users"][owner].get("password", False)
        if not password:
            raise ValueError("Password or access token is required")

        bot = Bot.from_credentials(
            server=address,
            username=owner,
            password=password,
            verify_ssl=verify_ssl,

        )
    else:
        bot = Bot(server=config["server"]["ip_address"], token=token)

    await bot.start()
    await bot.connected_event.wait()
    await bot.authorized_event.wait()

    async def add_user_to_chat(chat_id):
        for user in config["users"].keys():
            try:
                r = await bot.add_participant_to_chat(
                    chat_id=chat_id,
                    user_id=user
                )
            except Exception as e:
                print("Error:", e)
        print(f"{Fore.GREEN}Users have been added to '{chat_name}'{Style.RESET_ALL}")

    match config["chat"].get("type", False):
        case "channel":
            created_instance: CreateChannelResponse = await bot.create_channel(title=chat_name)
            print(f"{Fore.GREEN}Created '{chat_name}' channel {Style.RESET_ALL}")
            await add_user_to_chat(chat_id=created_instance.chat_id)
        case "group":
            created_instance: CreateGroupChatResponse = await bot.create_group_chat(title=chat_name)
            print(f"{Fore.GREEN}Created '{chat_name}' group chat {Style.RESET_ALL}")
            await add_user_to_chat(chat_id=created_instance.chat_id)
        case "personal":
            users = list(config["users"].keys())
            user_id = users[1] if users[0] == owner else users[0]
            created_instance: CreateP2PChatResponse = await bot.create_personal_chat(user_id=user_id)
            print(f"{Fore.GREEN}Created personal chat with {user_id} {Style.RESET_ALL}")
        case _:
            print("erre")
            return None

    return created_instance.chat_id


async def convert_voice_message_to_video(audio_file: Path):
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

    date_str, time_str = audio_path.stem.split("@", 1)[1].split("_")

    timestamp = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H-%M-%S")

    video_stream = (
        ffmpeg
        .input(str(cover_path), loop=1)  # -loop 1
        .filter("scale", 1920, 1080)  # 720p (растянет до 16:9)
        .drawtext(
            text=f"Telegram\n{timestamp}",
            fontcolor="white",
            fontsize=18,
            x="w-tw-20",  # отступ от правого края
            y="h-th-20",  # отступ от нижнего края
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


async def fill_chat(chat_id, convert_voice_message):
    map_message_ids = {}
    users_object = {}

    verify_ssl = config["server"].get("verify_ssl", False)
    address = config["server"]["address"]

    for user, data_ in config["users"].items():
        token = data_.get("access_token", False)
        if not token:
            password = data_.get("password", False)
            if not password:
                raise ValueError("Password or access token is required")
            bot = Bot.from_credentials(
                server=address,
                username=user,
                password=password,
                verify_ssl=verify_ssl,
            )
        else:
            bot = Bot(server=config["server"]["ip_address"], token=token)

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

    for message in data["messages"]:
        map_message_ids[message["id"]] = []
        file = message.get("file", "")

        try:
            if message.get("photo", False):
                r: SendFileResponse = await users_object[message["from_id"]].send_photo(
                    chat_id=chat_id,
                    file_path=telegram_export_dir / message["photo"],
                    preview_path=telegram_export_dir / message["photo"],
                )
                map_message_ids[message["id"]].append(r.message_id)

            elif message.get("media_type", False):
                if Path(file).is_file():
                    print(f"Message: {message['id']}, {file}")
                    continue
                match message["media_type"]:
                    case "voice_message":
                        if convert_voice_message:
                            file = await convert_voice_message_to_video(telegram_export_dir / check_file(file))
                        r: SendFileResponse = await users_object[message["from_id"]].send_document(
                            chat_id=chat_id, file_path=file)
                        map_message_ids[message["id"]].append(r.message_id)

                    case "animation":
                        r: SendFileResponse = await users_object[message["from_id"]].send_document(
                            chat_id=chat_id, file_path=telegram_export_dir / check_file(file))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "video_message":
                        r: SendFileResponse = await users_object[message["from_id"]].send_document(
                            chat_id=chat_id, file_path=telegram_export_dir / check_file(file))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "video_file":
                        r: SendFileResponse = await users_object[message["from_id"]].send_document(
                            chat_id=chat_id, file_path=telegram_export_dir / check_file(file))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "sticker" if message["mime_type"] == "video/webm":
                        r: SendFileResponse = await users_object[message["from_id"]].send_document(
                            chat_id=chat_id, file_path=telegram_export_dir / check_file(file))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "sticker" if message["mime_type"] == "image/webp":
                        r: SendFileResponse = await users_object[message["from_id"]].send_sticker(
                            chat_id=chat_id, file_path=telegram_export_dir / check_file(file))
                        map_message_ids[message["id"]].append(r.message_id)

                    case "sticker" if message["mime_type"] == "application/x-tgsticker":
                        r: SendMessageResponse = await users_object[message["from_id"]].send_message(
                            chat_id=chat_id,
                            text=message["sticker_emoji"],
                            parse_mode=ParseMode.TEXT
                        )
                        map_message_ids[message["id"]].append(r.message_id)

            elif message.get("file", False):
                r: SendFileResponse = await users_object[message["from_id"]].send_document(
                    chat_id=chat_id, file_path=telegram_export_dir / file)
                map_message_ids[message["id"]].append(r.message_id)

            if message["text_entities"]:
                if message.get("reply_to_message_id", False):
                    message_id = get_message_id(message["reply_to_message_id"])
                    if message_id is not None:
                        r: SendMessageResponse = await users_object[message["from_id"]].reply_message(
                            chat_id=chat_id,
                            text=build_content_from_text_entities(message["text_entities"], message["date_unixtime"]),
                            parse_mode=ParseMode.HTML,
                            message_id=message_id)
                    else:
                        r: SendMessageResponse = await users_object[message["from_id"]].send_message(
                            chat_id=chat_id,
                            text=build_content_from_text_entities(message["text_entities"], message["date_unixtime"]),
                            parse_mode=ParseMode.HTML)
                else:
                    r: SendMessageResponse = await users_object[message["from_id"]].send_message(
                        chat_id=chat_id,
                        text=build_content_from_text_entities(message["text_entities"], message["date_unixtime"]),
                        parse_mode=ParseMode.HTML)
                map_message_ids[message["id"]].append(r.message_id)

        except KeyError as e:
            print(
                f"{Fore.YELLOW}Skipped message from '{message['from_id']}', because this ID was not added to config.toml.{Style.RESET_ALL}")
        except FileNotIncluded as e:
            print(f"{Fore.YELLOW}Skipped message '{message['id']}'.", e, f"{Style.RESET_ALL}")

    print(f"{Fore.GREEN}✅ Chat transfer complete{Style.RESET_ALL}")

    print(f"{Fore.BLUE}Bots are shut down{Style.RESET_ALL}")
    for name, bot in users_object.items():
        await bot.shutdown()


async def main() -> None:
    chat_id = await create_chat_and_add_users()
    await fill_chat(chat_id=chat_id, convert_voice_message=IS_CONVERT_VOICE)


if __name__ == "__main__":
    asyncio.run(main())
