from colorama import Fore, Style
import orjson
import sys
import re
from tqdm import tqdm
from datetime import datetime

import asyncio
from pathlib import Path

import tomlkit
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

def load_context(config_path: str = "config.toml"):
    config_file = Path(config_path)

    with open(config_file, "r", encoding="utf-8") as f:
        config = tomlkit.load(f)
        print(f"{Fore.BLUE}Read {config_file.name}{Style.RESET_ALL}")

    bot_token = config["telegram_bot"].get("token", False)
    telegram_chat_id = config["telegram_bot"].get("chat_id", False)
    telegram_bot_enabled = config["telegram_bot"].get("chat_id", False)
    telegram_export_dir = Path(config["telegram_export_dir"])

    if not telegram_export_dir.exists():
        raise FileNotFoundError(
            f"Invalid Path to Telegram Export Dir: '{telegram_export_dir}'"
        )

    result_file = telegram_export_dir / "result.json"
    if not result_file.exists():
        raise FileNotFoundError(f"result.json not found in '{telegram_export_dir}'")

    with open(result_file, "rb") as f:
        data = orjson.loads(f.read())
        print(f"{Fore.BLUE}Read result.json{Style.RESET_ALL}")

    return config, data, bot_token, telegram_chat_id, telegram_bot_enabled, telegram_export_dir, config_file

def normalize_status(status) -> str:
    mapping = {
        ChatMemberStatus.CREATOR: "creator",
        ChatMemberStatus.ADMINISTRATOR: "administrator",
        ChatMemberStatus.MEMBER: "member",
        ChatMemberStatus.RESTRICTED: "restricted",
        ChatMemberStatus.LEFT: "left",
        ChatMemberStatus.KICKED: "kicked",
    }
    return mapping.get(status, str(status))


async def check_bot_ready(bot: Bot, chat_id: int) -> tuple[bool, str]:
    me = await bot.get_me()

    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=me.id)
    except TelegramForbiddenError:
        return False, "Бот не имеет доступа к чату или был удалён из него."
    except TelegramBadRequest as e:
        return False, f"Не удалось проверить чат. Проверьте chat_id: {e}"

    status = member.status

    if status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
        return False, "Бот не добавлен в указанный чат."

    if status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        return False, "Бот добавлен в чат, но не является администратором."

    return True, "OK"


async def enrich_users(config, data, config_path: Path, bot: Bot = None, telegram_chat_id: int = None) -> None:
    default_password = config.get("registration").get("default_password", False)
    users = config.get("users")

    if users is None:
        users = tomlkit.table()
        config["users"] = users
        config["users"].add(tomlkit.comment(f"Updated users {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    else:
        users.clear()

    registration = config["registration"].get("auto", False)

    added_count = 0
    skipped_no_from_id = 0
    skipped_no_from = 0

    for user in tqdm(data["messages"]):
        if user.get("from_id", False):
            if user["from"] is None:
                skipped_no_from += 1
                continue

            telegram_id = re.findall(r"\d+", user["from_id"])[0]

            if config["users"].get(telegram_id, False):
                continue

            user_type = re.findall(r"\D+", user["from_id"])[0]

            t = tomlkit.table()
            if registration:
                t.add(tomlkit.comment("Required only for registration user in TrueConf Server"))
                t["display_name"] = re.sub(r'[^\w\s]', '', user["from"], flags=re.UNICODE).strip(' ')
                t["password"] = default_password if default_password else ""
                t.add(tomlkit.comment(f"Required for fill chat (script build_chat.py)"))

            t["access_token"] = ""
            t["trueconf_id"] = ""
            t["telegram_id"] = telegram_id
            t["type"] = user_type

            if bot:
                t.add(tomlkit.comment("Additional info from telegram bot"))
                try:
                    member = await bot.get_chat_member(chat_id=int(telegram_chat_id), user_id=telegram_id)
                    tg_user = member.user
                    t["username"] = tg_user.username or ""
                    t["real_display_name"] = tg_user.full_name or ""
                    t["status"] = normalize_status(member.status)
                    t["is_bot"] = bool(tg_user.is_bot)

                except TelegramBadRequest as e:
                    t["status"] = "not_found_or_inaccessible"
                    t["username"] = t.get("username", "")
                    t["real_display_name"] = t.get("real_display_name", "")


                except TelegramForbiddenError as e:
                    t["status"] = "forbidden"

                except Exception as e:
                    t["status"] = "error"

                await asyncio.sleep(0.01)


            config["users"][user["from_id"]] = t
            added_count += 1
        skipped_no_from_id += 1

    with open(config_path, "w", encoding="utf-8", newline="") as f:
        print(config_path)
        tomlkit.dump(config, f)

    print(f"Users added: {added_count}")
    print(f"Skipped without from_id: {skipped_no_from_id}")
    print(f"Skipped without from: {skipped_no_from}")
    print(f"{Fore.GREEN}File 'config.toml' updated successfully {Style.RESET_ALL}")


async def main(config_path: str = "config.toml") -> None:
    config, data, bot_token, telegram_chat_id, telegram_bot_enabled, telegram_export_dir, config_file = load_context(config_path)

    if telegram_bot_enabled:
        if telegram_chat_id and bot_token:
            bot = Bot(bot_token)
            try:
                me = await bot.get_me()
                print(f"Бот авторизован: @{me.username} (id={me.id})")

                ok, message = await check_bot_ready(bot, int(telegram_chat_id))
                if not ok:
                    print(message)
                    return

                await enrich_users(config, data, config_file, bot, telegram_chat_id)
            finally:
                await bot.session.close()
        else:
            print(f"Для работы бота нужно:\n\n- токен\nID чата\n- бот должен быть администратором")
    else:
        await enrich_users(config, data, config_file)

def parse_users(config_path: str = "config.toml") -> None:
    asyncio.run(main(config_path))

if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.toml"
    parse_users(config_path)





