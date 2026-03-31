from colorama import Fore, Style
import orjson
import sys
import re
from transliterate import translit
from datetime import datetime

import asyncio
from pathlib import Path

import tomlkit
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

with open("config.toml", "rb") as f:
    config = tomlkit.load(f)
    print(f"{Fore.BLUE}Read config.toml{Style.RESET_ALL}")

BOT_TOKEN = config["telegram_bot"].get("token", False)
TELEGRAM_CHAT_ID = config["telegram_bot"].get("chat_id", False)
TELEGRAM_EXPORT_DIR = Path(config["telegram_export_dir"])

if TELEGRAM_EXPORT_DIR.exists():
    with open(TELEGRAM_EXPORT_DIR / "result.json", "rb") as f:
        data = orjson.loads(f.read())
        print(f"{Fore.BLUE}Read result.json{Style.RESET_ALL}")
else:
    print(
        f"{Fore.RED}ERROR! Invalid Path to Telegram Export Dir:{Style.RESET_ALL} "
        f"{Fore.GREEN}'{TELEGRAM_EXPORT_DIR}'{Style.RESET_ALL}"
    )
    sys.exit()

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


async def enrich_users(bot: Bot = None) -> None:
    default_password = config.get("registration").get("default_password", False)
    users = config.get("users")

    if users is None:
        users = tomlkit.table()
        config["users"] = users
        config["users"].add(tomlkit.comment(f"Updated users {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    else:
        users.clear()

    registration = config["registration"].get("auto", False)

    for user in data["messages"]:
        if user.get("from_id", False):
            if user["from"] is None:
                continue
            user_id = re.sub(r'[^a-z0-9]+', '_', translit(
                value=user["from"],
                language_code="ru",
                reversed=True,
                strict=True
            ).lower().replace("'", '')).strip('_')

            if config["users"].get(user_id, False):
                continue

            telegram_id = re.findall(r"\d+", user["from_id"])[0]
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
                    member = await bot.get_chat_member(chat_id=int(TELEGRAM_CHAT_ID), user_id=telegram_id)
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

                await asyncio.sleep(0.05)


            config["users"][user_id] = t


    with open("config.toml", "w") as f:
        tomlkit.dump(config, f)
    print(f"{Fore.GREEN}File 'config.toml' updated successfully {Style.RESET_ALL}")


async def main() -> None:


    if TELEGRAM_CHAT_ID and BOT_TOKEN:
        bot = Bot(BOT_TOKEN)
        try:
            me = await bot.get_me()
            print(f"Бот авторизован: @{me.username} (id={me.id})")

            ok, message = await check_bot_ready(bot, int(TELEGRAM_CHAT_ID))
            if not ok:
                print(message)
                return

            await enrich_users(bot)
        finally:
            await bot.session.close()
    else:
        await enrich_users()



if __name__ == "__main__":
    asyncio.run(main())





