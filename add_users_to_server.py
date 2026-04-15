import sys
from pathlib import Path

import httpx
import tomlkit
from colorama import Fore, Style


def register_users(config_path: str = "config.toml") -> dict:
    config_file = Path(config_path)
    with open(config_file, "r", encoding="utf-8") as f:
        config = tomlkit.load(f)
        print(f"{Fore.BLUE}Read {config_file.name}{Style.RESET_ALL}")

    server_address = config["server"].get("address", None)
    web_port = config["server"].get("web_port", None)
    access_token = config["server"].get("access_token", None)
    verify_ssl = config["server"].get("verify_ssl", False)

    if not server_address or not web_port:
        raise ValueError("Заполните адрес сервера и веб-порт")
    if not access_token:
        raise ValueError("Заполните access_token для регистрации пользователей")

    email_domain = config["registration"].get("email_domain")
    if not email_domain:
        with httpx.Client(verify=verify_ssl) as client:
            response = client.get(f"https://{server_address}:{web_port}/api/v4/server")
            response.raise_for_status()
            email_domain = response.json().get("product", {}).get("display_name")

    users = config.get("users", {}) or {}
    if not users:
        raise ValueError("В конфиге нет пользователей для регистрации")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    results = {
        "created": [],
        "already_exists": [],
        "errors": [],
    }

    with httpx.Client(verify=verify_ssl) as client:
        for user_key, user_data in users.items():
            payload = {
                "display_name": user_data.get("display_name", ""),
                "email": f"{user_data.get('trueconf_id', None)}@{email_domain}",
                "id": user_data.get("trueconf_id", None),
                "is_active": True,
                "password": user_data.get("password", None),
            }

            response = client.post(
                url=f"https://{server_address}:{web_port}/api/v4/users",
                json=payload,
                headers=headers,
            )

            try:
                response_json = response.json()
            except Exception:
                response_json = {}

            if response.status_code == 400:
                errors = response_json.get("error", {}).get("errors", [])
                reason = errors[0].get("reason") if errors else None
                if reason == "uniqueValueAlreadyInUse":
                    print(f"{Fore.YELLOW}⚠️ {user_key} already exists on the server{Style.RESET_ALL}")
                    results["already_exists"].append(
                        {
                            "display_name": user_data.get("display_name", ""),
                            "trueconf_id": user_data.get("trueconf_id", ""),
                            "telegram_id": user_data.get("telegram_id", ""),
                        }
                    )
                    continue

            if response.status_code == 200:
                print(f"{Fore.GREEN}✅ {user_key} has been added to the server{Style.RESET_ALL}")
                results["created"].append(
                    {
                        "display_name": user_data.get("display_name", ""),
                        "trueconf_id": user_data.get("trueconf_id", ""),
                        "telegram_id": user_data.get("telegram_id", ""),
                    }
                )
                continue

            error_message = response_json.get("error", {}).get("message", "Неизвестная ошибка")
            error_details = response_json.get("error", {}).get("errors", [])
            details_text = error_details[0] if error_details else "—"
            print(
                f"{Fore.RED}🔴 Error for user: {user_key}\n"
                f" - Status code: {response.status_code} {error_message}\n"
                f" - Description: {details_text}{Style.RESET_ALL}"
            )
            results["errors"].append(
                {
                    "user": user_key,
                    "status_code": response.status_code,
                    "message": error_message,
                    "details": details_text,
                }
            )

    return results


def main(config_path: str = "config.toml"):
    return register_users(config_path)


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.toml"
    main(config_path)