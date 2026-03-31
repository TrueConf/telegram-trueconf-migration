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

    email = config["registration"].get("email_domain")

    if not email:
        email = httpx.Client(verify=verify_ssl).get(f"https://{server_address}:{web_port}/api/v4/server").json().get(
            "product").get("display_name")

    users = config["users"]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }

    for user, data in users.items():
        data = {
            "display_name": data["display_name"],
            "email": f"{user}@{email}",
            "id": data.get("trueconf_id", None),
            "is_active": True,
            "password": data.get("password", None),

        }
        with httpx.Client(verify=verify_ssl) as client:
            r = client.post(
                url=f"https://{server_address}:{web_port}/api/v4/users",
                json=data,
                headers=headers
            )

            match r.status_code:
                case 400 if r.json().get("error").get("errors")[0].get("reason") == "uniqueValueAlreadyInUse":
                    print(f"{Fore.YELLOW}⚠️ {user} already exists on the server{Style.RESET_ALL}")

                case 200:
                    print(f"{Fore.GREEN}✅ {user} has been added to the server{Style.RESET_ALL}")
                case _:
                    print(f"{Fore.RED}🔴 Error for user: {user}\n"
                          f" - Status code: {r.status_code} {r.json().get('error').get("message")}\n"
                          f" - Description: {r.json().get('error').get('errors')[0]}{Style.RESET_ALL}")

                    break


if __name__ == "__main__":
    main()
