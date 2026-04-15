<p align="center">
  <a href="https://trueconf.com" target="_blank" rel="noopener noreferrer">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/TrueConf/.github/refs/heads/main/logos/logo-dark.svg">
      <img width="150" alt="trueconf" src="https://raw.githubusercontent.com/TrueConf/.github/refs/heads/main/logos/logo.svg">
    </picture>
  </a>
</p>

<h1 align="center">🛡️ Secure сhat transfer from Telegram to TrueConf</h1>

<p align="center">Looking for a secure messenger? Transfer all your chats from Telegram to TrueConf in just a few clicks. Migration is supported only in the on-premise solutions <a href=\"https://trueconf.ru/products/server/server-videokonferenciy.html\">TrueConf Server</a> / <a href=\"https://trueconf.ru/products/enterprise/trueconf-enterprise.html\">TrueConf Enterprise</a>.</p>
<p align="center">
     <a href="https://pypi.org/project/python-trueconf-bot" target="_blank">
      <img alt="PyPI - Version" src="https://img.shields.io/pypi/v/python-trueconf-bot?label=python-trueconf-bot">
</a>
    <a href="https://t.me/trueconf_chat" target="_blank">
        <img src="https://img.shields.io/badge/telegram-group-blue?style=flat-square&logo=telegram" />
    </a>
    <a href="https://discord.gg/2gJ4VUqATZ">
        <img src="https://img.shields.io/badge/Discord-%235865F2.svg?&logo=discord&logoColor=white" />
    </a>
</p>
<p align="center">
  <img src="docs/head_en.png" alt="Telegram and TrueConf" width="800" height="auto">
</p>

<p align="center">
  <a href="./README.md">English</a> /
  <a href="./README-ru.md">Русский</a>
</p>

> [!CAUTION]
> These instructions apply to TrueConf Server v5.5.3 or later.
If you are running an earlier version, [update the server](https://trueconf.com/products/server/howto-update-trueconf-server.html) first.

## Getting started

To migrate chats from Telegram to TrueConf, you need to:

1. [Export a chat from Telegram](#telegram-chat-export).
1. [Set the parameters in the configuration
file](#configuration-file-settings).
1. [If necessary,
create](#automatic-collection-of-user-information) user
accounts on the video conferencing server in advance.
1. [Run the script](#chat-migration).

You will also need:

- Installed [Telegram Desktop](https://desktop.telegram.org/) application
- Deployed [TrueConf
Server](https://trueconf.com/products/tcsf/free-video-conferencing-server.html)
version 5.5.3 or higher
([guide](https://trueconf.com/docs/server/en/admin/server-part/))
- Python 3.11 or higher
- A little bit of patience.

## Downloading the repository and setting up the environment

To download files/scripts from the main page of the repository, click the
**Code** button and select **Download ZIP**. Next, unpack the archive to the
selected directory.

### Python

To work with these scripts, you need to have Python 3.11 or higher. If you are
using Windows, you can download Python from the [official
website](https://www.python.org/). On Linux and macOS, Python is usually
pre-installed. Check your version with this command:

```bash
> python --version
Python 3.12.4
```

> [!IMPORTANT]
> If necessary, update your version; otherwise, the script will not work.

### Environment Setup

Create a virtual environment and install the dependencies (preferably using [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
```

## Telegram chat export

After installing and signing in to Telegram Desktop, you will be able to access
all your chats.

> [!TIP]
> If you are an organization administrator and do not have access to certain conversations, you can ask any chat participant to export the history instead of you.

To export the history:

1. Go to the chat and click the button with three dots in the header:

<p align="center"><img width=400px src="docs/tg_more_en.png"></p>

1. Select **Export chat history** in the menu.
1. In the export settings window:

   - Check the boxes for the types of media you need to export
   - Set a size limit for files
   - Choose the **JSON** format
   - Set the path for saving the file or use the default path
`Downloads/Telegram Desktop/`
   - Set the range, for example, from the first message to the current date, from
01.02.2022 12:00 to 03.03.2023 19:00, etc.

<p align="center"><img width=400px src="docs/export_setting_window_en.png"></p>

1. Click the **Export** button.

The application will start saving the chat with selected settings. You can close
this window, if it obstructs the view.

> [!CAUTION] 
> Wait for the operation to complete fully. If you have selected a date range and see that the messages have already been exported, do not cancel the process to avoid file corruption.

## Configuration file settings

### Description

> [!NOTE]
> We use the [TOML](https://toml.io/) language to configure settings.

Open the `config.toml` file. You will see the following structure:

```toml
telegram_export_dir = ""

[telegram_bot]
token = ""
chat_id = ""

[server]
address = "" # IP or domain.name
web_port = 443
verify_ssl = false # or true if needed
access_token = ""

[chat]
type = "" # available: personal, group, channel, supergroup
name = ""
supergroup_topic_name_template = "{topic} | {supergroup}" # only for supergroup. Available: topic – topic's name, supergroup's name from name param
owner = "" # who created chat

[chat.datetime]
view_original_time_in_message = false # or true if needed
timezone = "GMT" # need if view_original_time_in_message = true
caption = "" # example: f"{caption}{dt}"

[chat.voice_message]
convert_voice_message_to_video = false
cover_image = "cover/en.png" # by default "cover/en.png"

[registration]
auto = false # or true if needed
email_domain = "" # If it does not exist, the external server name will be substituted.
default_password = ""

[users]

[users.trueconf_id]
display_name = ""
password = ""
access_token = ""
telegram_id = ""
type = ""
```

To transfer chats successfully, you need to fill out the configuration file
according to the following description:

| Section            | Parameter                         | Description                                                                                                                                                                                                                                                         |
|--------------------|-----------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|                    | telegram_export_dir               | Path to the folder containing the exported Telegram chat                                                                                                                                                                                                            |
| telegram_bot       |                                   |                                                                                                                                                                                                                                                                     |
|                    | token                             | Bot token from [@BotFather](https://t.me/BotFather)                                                                                                                                                                                                                 |
|                    | chat_id                           | Chat ID. You can get it from [@userinfobot](https://t.me/userinfobot)                                                                                                                                                                                               |
| server             |                                   | TrueConf Server settings                                                                                                                                                                                                                                            |
|                    | address                           | Domain name or IP address of the TrueConf Server                                                                                                                                                                                                                    |
|                    | web_port                          | HTTPS port in use. Defaults to `443`.                                                                                                                                                                                                                               |
|                    | verify_ssl                        | SSL certificate verification. Set to `true` if you are using a trusted certificate.                                                                                                                                                                                 |
|                    | access_token                      | Security token for API access.                                                                                                                                                                                                                                      |
| chat               |                                   | Settings for the new chat in TrueConf Server                                                                                                                                                                                                                        |
|                    | name                              | Chat name                                                                                                                                                                                                                                                           |
|                    | type                              | Chat type: `personal` (one-to-one chat), `group` (group chat), `channel` (channel), `supergroup` (group chat with a forum structure: themes, topics).                                                                                                               |
|                    | supergroup_topic_name_template    | Template for the name of the forum being migrated to TrueConf                                                                                                                                                                                                       |
|                    | owner                             | Creator (for `personal`) and chat owner (for `group`, `supergroup`, and `channel`)                                                                                                                                                                                  |
| chat.datetime      |                                   | Settings for displaying the original Telegram message date and time.                                                                                                                                                                                                |
|                    | view_original_time_in_message     | If `true`, the date and time of sending will be added to each text message.                                                                                                                                                                                         |
|                    | timezone                          | Time zone setting. You must specify the correct time zone for most users in the chat. Defaults to `GMT` (UTC).                                                                                                                                                      |
|                    | caption                           | Optionally, you can add a label before the date and time. For example, `Sent:` or `Date:`.                                                                                                                                                                          |
| chat.voice_message |                                   | Settings for migrating voice messages                                                                                                                                                                                                                               |
|                    | convert_voice_message_to_video    | If `true`, all voice messages will be converted to `mp4` video format. Requires the [ffmpeg](https://ffmpeg.org/) package to be preinstalled.                                                                                                                       |
|                    | cover_image                       | If `convert_voice_message_to_video = true`, the specified placeholder image will be used.                                                                                                                                                                           |
|                    | data_time                         | If `true`, the date and time the original Telegram message was sent will be added to the **text message**.                                                                                                                                                          |
| chat.stickers      |                                   |                                                                                                                                                                                                                                                                     |
|                    | convert_telegram_stickers_to_webp | If `true`, every animated Telegram sticker (**.tgs**) will be converted to **webp**. This requires system libraries to be installed in the OS. If `false`, the sticker is replaced with an emoji.                                                                   |
| registration       |                                   | Settings for automatically adding users to TrueConf Server.                                                                                                                                                                                                         |
|                    | auto                              | If `true`, the `display_name` and `password` parameters will be added to [users] when using `parse_users.py`.                                                                                                                                                       |
|                    | email_domain                      | If you use corporate email, specify the domain that will be used in the `email` field when automatically adding a user. For example, if you use the `mail.example.com` domain, then a user named `user` will be assigned the email address `user@mail.example.com`. |
|                    | default_password                  | Common password for all accounts. Automatically fills the `password` parameter when using the `parse_users.py` script.                                                                                                                                              |
| users              |                                   | Section for configuring user accounts (chat participants). It can be filled automatically using `parse_users.py`.                                                                                                                                                   |
|                    | display_name, password            | Automatically filled in if `registration.auto = true`. Required for automatic user creation using `add_users_to_server.py`.                                                                                                                                         |
|                    | telegram_id, type                 | Numeric Telegram ID and user type (`user`, `channel`). Automatically filled in when using `parse_users.py`.                                                                                                                                                         |
|                    | access_token                      | User authorization token in TrueConf Chatbot Connector (_TTL = 1 month_). Required for chat migration. If not specified, `password` is used.                                                                                                                        |

> [!TIP]
> **Do I really need to fill so many parameters 🤯?** Actually, no. To simplify this process, we provided scripts, described below.

### Automatic collection of user information

If the Telegram chat has a large number of participants, filling out the config
file can be quite discouraging :cry:. Due to this reason, the TrueConf team
created a script [parse_users.py](parse_users.py) which automatically populates the `[users]`
section.

> [!NOTE] 
> **What does the script do?** It parses the exported `result.json` file and generates the list of users.

1. Specify the path to the folder with the exported chat In the `config.toml`
file:
   ```toml
   telegram_export_dir = "~/Downloads/Telegram Desktop/ChatExport_2025-09-05"
   ```

1. To collect additional data such as the username and the self-defined user name (`real_display_name`), we recommend creating a bot via [@BotFather](https://t.me/BotFather). 
   Then specify the bot token and the target chat ID in `config.toml` (you can get it using [@userinfobot](https://t.me/userinfobot)).

1. Run the script in the configured environment:

   ```shell
   uv run parse_users.py
   ```

1. If the operation is completed successfully, you will receive a notification
about the correct update of the configuration file:

   ```shell
   The file 'config.toml' has been successfully updated
   ```

1. In the `[users]` section of the `config.toml` file, you will have all the
participants listed with the following parameters:

   ```toml
   [users]
   [users.john_doe]
   access_token = ""
   trueconf_id = ""
   telegram_id = "12345678"
   type = "user"
   ```

If you will automatically add users to TrueConf Server, specify the following
parameters in the `config.toml` file:

```toml
[registration]
auto = true # Required
email_domain = "mail.example.com" # Optional (read the description)
default_password = "12345678" # Optional (read the description)
```

and restart the script.

### How to add users automatically to TrueConf Server

To migrate conversations from Telegram to TrueConf, all users participating in the chat must be registered in TrueConf Server. 
If you **are not using LDAP**, you can use the [add_users_to_server.py](add_users_to_server.py) script for automatic user provisioning.

> [!IMPORTANT]
> If your infrastructure is already configured, proceed to the next section.

Before running the script, make sure that all data in the `[users]` block meets your expectations.  
Specify the required TrueConf ID (the part before `@`), and adjust the display name (`display_name`) and password (`password`) if necessary:

```toml
# Example:
[users.john]
trueconf_id = "john_doe"
display_name = "John Doe"
password = "verystrongpassword1357"
```

> [!NOTE]
> Double-check all new users. 
> If you made a mistake, you can delete all created users using `delete_users_from_server.py` and repeat the registration process.

The script also requires an `access_token` to access the TrueConf Server API. You can obtain it in one of the following ways:

1. In the TrueConf Server control panel.

   Go to **Web → Security** and copy the API token.

> [!CAUTION]
> This type of token does not expire by default, provides access to the entire server API, and must be stored as an administrator secret.

2. Via an OAuth application (recommended).

   Create an [OAuth application](https://trueconf.com/docs/server/en/admin/api/), grant it only the required permissions, and send a request to `https://domain.name/api/v4/token` to exchange the `client_id` and `client_secret` for an `access_token`.

> [!NOTE]
> By default, an OAuth token is valid for 1 hour, which makes this option more secure for migration and automation scenarios.

After verifying all the data, run the script:

```shell
uv run add_users_to_server.py
```

For each user, you will receive one of the following responses:

```
✅ A user has been added to the server

⚠️ The user already exists on the server

 🔴 Error for user
```

### For Configured Infrastructures (When Using LDAP)

If your infrastructure uses LDAP and you need to migrate a chat with a large number of participants — more than 20 users — manually collecting an `access_token` for each user may be too time-consuming and impractical.
In this case, we recommend performing the migration outside business hours by temporarily switching TrueConf Server from **LDAP** to **Registry** mode.
You can then use the `add_users_to_server.py` script as described in the section “[Automatic User Provisioning in TrueConf Server (Without LDAP)](#automatic-user-provisioning-in-trueconf-server-without-ldap)”,
add the required users to the server, and complete the chat migration. Once the migration is finished, the server can be switched back to LDAP.
If switching to Registry is not possible even for a short period of time, follow the instructions in the next section.

We recommend the following procedure:

1. In `config.toml`, enable automatic registration in advance and set a default password (additional details are available in the [section](#automatic-user-collection)):

   ```toml
   [registration]
   auto = true
   default_password = "12345678"
   ```
   
2.	Run parse_users.py to automatically populate the `[users]` section.
3.	Manually specify the correct `trueconf_id` for each user:

   ```toml
   [users.john]
   trueconf_id = "john_doe"
   telegram_id = "44556677"
   password = "12345678"
   ```
   
4.	Outside business hours, temporarily switch TrueConf Server from **LDAP** mode to **Registry** mode without automatic user migration.
5.	Register the users on the server using the `add_users_to_server`.py script.
6.	Perform the [chat migration](#chat-migration).
7.	After the migration has been successfully completed, switch the server back to **LDAP**.

If switching to **Registry** is not possible even for a short period of time, use the instructions in the next section.

### Obtaining an access_token for Chat API Authorization (If Switching from LDAP to Registry Is Not Possible)

An `access_token` is required to authorize requests to the chat API. 
To obtain it, you need to send a **POST** request with the login and password of a TrueConf Server account (see the [documentation](https://trueconf.com/docs/chatbot-connector/en/connect-and-auth/#access-token)).

However, in an LDAP-based infrastructure, this creates a practical problem:
as a rule, the TrueConf Server administrator does not know the passwords of user accounts, because authentication is performed through domain credentials.
Requesting employees’ corporate account passwords is both insecure and unacceptable, since it effectively means asking for access to their domain accounts.

Due to this reason, TrueConf team created an [HTML page](chatbot/ru/index.html)
to simplify this process. What should I do with it? Just add it to your TrueConf
Server or the required TrueConf Enterprise node.

#### How to add the page to the TrueConf web server

1. Copy the [`chatbot`](chatbot) folder to the following path:

   **Windows (PowerShell):**
   ```shell
   Copy-Item -Path "D:\chatbot" -Destination "C:\Program Files\TrueConf Server\httpconf\site" -Recurse
   ```

   **Linux:**
   ```shell
   sudo cp ~/chatbot /opt/trueconf/server/srv/site/
   ```
1. Restart the **TrueConf Web Manager** service:

   **Windows (PowerShell):**
   ```shell
   Restart-Service -Name "TrueConf Web Manager"
   ```

   **Linux:**
   ```shell
   sudo systemctl restart trueconf-web
   ```

> [!CAUTION]
> When TrueConf Server is updated, the `chatbot` directory will be deleted from the server.

#### How to get the token

Ask each user, who will be added to the chat, to get the access_token in the
following way:

1. Open the page `https://server.address/chatbot/ru/index.html` in your browser.
Enter your login (TrueConf ID) and password in the input fields, then click
**Get token**:
<p align="center">
  <img src="docs/chatbot_auth_en.png" alt="Chatbot Auth Page" width="800" height="auto">
</p>


1. In case of success a token will be displayed. Copy it or download as a file
that can be later sent to the administrator:
<p align="center">
  <img src="docs/chatbot_token_en.png" alt="Chatbot Auth Page" width="800" height="auto">
</p>

#### What to Do with the `access_token` After Obtaining It

Once users have received their `access_token` values, the administrator must add them to the `config.toml` file in the `[users]` section for the corresponding participants.

For each user, fill in the `access_token` field in their block:

```toml
[users.john]
trueconf_id = "john_doe"
access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
telegram_id = "44556677"
```

> [!IMPORTANT]
> Make sure that each token is inserted into the block of the user it actually belongs to. Otherwise, messages may be migrated under the wrong identity.

Once the access_token field has been filled in for all participants, you can proceed to the next step — [chat migration](#chat-migration).

## Chat migration

You've finally made it to this step! To transfer a chat, specify its name, type,
and owner in the configuration:

```toml
[chat]

#Example
name = "Secret chat"
type = "group" # available types are as follows: personal, group, supergroup, channel
owner = "sherlock" # who created chat
```

### Date and time synchronization

By default, TrueConf Server does not allow a message to be sent with a past date.
If it is important for you to check the date and time of the original message,
adjust the following settings:

- Set `view_original_time_in_message` to `true`
- Set the time zone, for example, `Europe/Moscow`
- If necessary, specify a caption for the date and time. Make sure to leave a
**space** at the end of the line.

```toml
[chat.datetime]

veiw_original_time_in_message = true
timezone = "Europe/Moscow"
caption = "Sent: "
```

In this case each text message will have this caption at the bottom
`Sent: 01.09.2025 14:10:00 +0300`.

### Conversion of voice messages from .ogg to .mp4

Voice messages in Telegram are in the **ogg** format. TrueConf client
applications do not support this format. For the sake of convenience, you can
convert all audio messages to video with a `cover_image`. 

> [!IMPORTANT]
> To render timestamps on video, FFmpeg must be installed with `drawtext` filter support. Before enabling this feature, please check your environment:
> 
> ```bash
> uv run check_ffmpeg.py
> ```
> 
> If the check passes successfully (**FFmpeg OK** ✅), you can proceed with the configuration.

To do it:

1. In the config file, enter `convert_voice_message_to_video = true`.
1. Choose the cover localization: `cover/ru.png` (in Russian) or `cover/en.png`
(in English). If necessary, you can change the cover to your own by writing
`cover_image = "path/to/cover_image.png"`.

Example:

```toml
[chat.voice_message]  
convert_voice_message_to_video = true  
cover_image = "path/to/cover_image.png"
```

Additionally, in the bottom right corner you will see additional information: the
export source and the time when the original recording was made.

<p align="center">
  <img src="docs/example_voice_message_en.png" alt="Chatbot Auth Page" width="800" height="auto">
</p>

### Converting Telegram Stickers (tgs) to WebP

Animated Telegram stickers are in **.tgs** format, which is a [Lottie](https://github.io) animation archive.
You can disable the conversion of Telegram stickers to WebP using the `chat.stickers.convert_telegram_stickers_to_webp` parameter. In this case, they will be sent simply as emojis.

> [!IMPORTANT]
> Conversion relies on system libraries that must be available on your system when the migration script is executed.

#### Windows

The **Cairo** system library is required. You can install it using [MSYS2](https://msys2.org). Follow these steps:

1. Run the following command in the MSYS2 terminal:

   ```bash
   pacman -Syu
   
2. If the console displays a message like `warn: terminate MSYS2 without returning to shell and check for updates again` — close and restart the MSYS2 terminal.
3. Install the library:

   ```bash
   pacman -S mingw-w64-x86_64-cairo
   ```

### Migration start

To start migration, run the command in the terminal:

```shell
uv run build_chat.py
```

> [!WARNING]
> If the chat type is either `group`, `supergroup` or `channel`, a new chat copy will be created each time the script is executed.

> [!TIP]
> If you, as an administrator, want to take full control over the migration process, specify your TrueConf ID in the `owner` parameter.

Later, you can always transfer chat rights to another user in TrueConf client
application.

If migration is completed successfully, a copy of the Telegram chat will be
created:

🎬 [Watch the video on YouTube](https://youtu.be/D52e83ABdz0)
