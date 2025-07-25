import sys
import httpx
import tomlkit
from colorama import Fore, Style


def add_users_to_server(users, email_domain, address, access_token, verify_ssl):
    url = f"https://{address}/api/v4/users"
    params = {
        "access_token": access_token,
    }

    headers = {
        "Content-Type": "application/json",
    }

    for user, data in users.items():
        data = {
            "display_name": data["display_name"],
            "email": f"{user}@{email_domain}",
            "id": user,
            "is_active": True,
            "password": data["password"],

        }
        with httpx.Client(verify=verify_ssl) as client:
            r = client.post(url, json=data, headers=headers, params=params)

            match r.status_code:
                case 400 if r.json().get("error").get("errors")[0].get("reason") == "uniqueValueAlreadyInUse":
                    print(f"{Fore.YELLOW}⚠️ {user} already exists on the server{Style.RESET_ALL}")

                case 200:
                    print(f"{Fore.GREEN}✅ {user} has been added to the server{Style.RESET_ALL}")
                case _:
                    print(f"{Fore.RED}🔴 Error for user: {user}\n"
                          f" - Status code: {r.status_code} {r.json().get('error').get("message")}\n"
                          f" - Description: {r.json().get('error').get('errors')[0]}{Style.RESET_ALL}")


def main():
    with open("config.toml", "rb") as f:
        config = tomlkit.load(f)
        print(f"{Fore.BLUE}Read config.toml{Style.RESET_ALL}")

    server_address = config["server"]["address"]
    server_access_token = config["server"].get("access_token")
    verify_ssl= config["server"].get("verify_ssl", False)
    if not server_access_token:
        with httpx.Client(verify=verify_ssl) as client:
            url = f"https://{server_address}/oauth2/v1/token"
            data = {
                    "grant_type": "client_credentials",
                    "client_id": config["server"].get("client_id"),
                    "client_secret": config["server"].get("client_secret")

                }

            headers = {
                "Content-Type": "application/json",
            }


            r = client.post(url=url, json=data, headers=headers)

            match r.status_code:
                case 200:
                    server_access_token = r.json()["access_token"]
                case _:
                    print(f"{Fore.RED}🔴 Error"
                          f" - Status code: {r.status_code} {r.json().get('error').get('message')}\n"
                          f" - Description: {r.json().get('error').get('errors')[0]}{Style.RESET_ALL}")
                    sys.exit(1)



    email = config["registration"].get("email_domain")

    if not email:
        email = httpx.Client(verify=verify_ssl).get(f"https://{server_address}/api/v4/server").json().get("product").get("display_name")

    users = config["users"]

    add_users_to_server(users, email, server_address, server_access_token, verify_ssl)


if __name__ == "__main__":
    main()
