import sys
import httpx
import tomlkit
from colorama import Fore, Style

def main():
    with open("config.toml", "r", encoding="utf-8") as f:
        config = tomlkit.load(f)
        print(f"{Fore.BLUE}Read config.toml{Style.RESET_ALL}")

    server_address = config["server"].get("address", None)
    web_port = config["server"].get("web_port", None)
    access_token = config["server"].get("access_token", None)
    verify_ssl = config["server"].get("verify_ssl", False)
    if not access_token:
        with httpx.Client(verify=verify_ssl) as client:
            print(f"{Fore.RED}🔴 Check access_token!")
            sys.exit(1)

    users = config["users"]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }

    for user, data in users.items():
        print(user)
        with httpx.Client(verify=verify_ssl) as client:
            r = client.delete(url=f"https://{server_address}:{web_port}/api/v4/users/{user}", headers=headers)

            match r.status_code:
                case 200:
                    print(f"{Fore.GREEN}✅ {user} has been delete to the server{Style.RESET_ALL}")
                case _:
                    print(f"{Fore.RED}🔴 Error for user: {user}\n{Style.RESET_ALL}", r.text)
                    # f" - Status code: {r.status_code} {r.json().get('error').get("message")}\n"
                    # f" - Description: {r.json().get('error').get('errors')[0]}{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
