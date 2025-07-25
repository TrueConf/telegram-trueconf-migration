from colorama import Fore, Style
import orjson
import sys
from pathlib import Path
import re
from transliterate import translit
import tomlkit
from datetime import datetime

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

        t = tomlkit.table()

        if registration:
            t.add(tomlkit.comment("Required only for registration user in TrueConf Server"))
            t["display_name"] = re.sub(r'[^\w\s]', '', user["from"], flags=re.UNICODE).strip(' ')
            t["password"] = default_password if default_password else ""
            t.add(tomlkit.nl())
            t.add(tomlkit.comment(f"Required for fill chat (script build_chat.py)"))

        t["access_token"] = ""
        t["telegram_id"] = re.findall(r"\d+", user["from_id"])[0]
        t["type"] = re.findall(r"\D+", user["from_id"])[0]


        trueconf_id = re.sub(r'[^a-z0-9]+', '_', translit(
            value=user["from"],
            language_code="ru",
            reversed=True,
            strict=True
        ).lower().replace("'",'')).strip('_')

        config["users"][trueconf_id] = t


with open("config.toml", "w") as f:
    tomlkit.dump(config, f)
print(f"{Fore.GREEN}File 'config.toml' updated successfully {Style.RESET_ALL}")


