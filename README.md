<div align="center">

# 🥝 KiwiTap

### A Telegram Mini App where every tap grows your kiwi empire.

Tap for points, build a passive-income farm, complete missions, invite friends, and climb the league rankings — all from Telegram.

![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Backend-Flask-000000?logo=flask&logoColor=white)
![Telegram](https://img.shields.io/badge/Platform-Telegram%20Mini%20App-26A5E4?logo=telegram&logoColor=white)
![Database](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white)

</div>

---

## ✨ Features

- **Tap-to-earn gameplay** with energy, tap-power upgrades, and temporary Frenzy boosts
- **Passive income** from upgradeable farm cards, including earnings while away
- **Daily rewards** with streak bonuses
- **Missions and promo codes** with configurable rewards and usage limits
- **Referral rewards** and a friends list
- **Leagues and leaderboards** to track player progress
- **Telegram bot integration** for launch, balance checks, and admin access
- **Web-based admin panel** for player management, game settings, cards, missions, promo codes, and broadcasts
- **SQLite storage** that initializes its tables on startup

## 🧰 Built With

- Python
- Flask
- pyTelegramBotAPI
- SQLite
- Telegram Mini Apps JavaScript SDK
- Tailwind CSS and Google Fonts, loaded by the web pages

## 🚀 Getting Started

### Requirements

- Python 3
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A publicly reachable **HTTPS** URL for the Mini App

### 1. Get the project

```bash
git clone https://github.com/aily-dev/KiwiTap.git
cd KiwiTap
```

### 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install Flask pyTelegramBotAPI
```

On Windows, activate the virtual environment with:

```powershell
.venv\Scripts\activate
```

### 3. Configure the environment

Set the required bot token and the HTTPS URL where the app will be served:

```bash
export BOT_TOKEN="your-telegram-bot-token"
export WEBAPP_URL="https://your-public-domain.example"
```

Optional settings:

```bash
export ADMIN_IDS="123456789,987654321"
export ADMIN_KEY="choose-a-long-random-secret"
export PORT="8000"
```

`ADMIN_IDS` is a comma-separated list of Telegram user IDs allowed to administer the game. `ADMIN_KEY` enables admin-panel access with a shared key. Keep both values private.

### 4. Run

```bash
python3 bot.py
```

The Flask app listens on port `8000` by default, or on the port specified by `PORT`. The Telegram bot starts polling when the application launches. Configure your HTTPS domain or reverse proxy to route traffic to this server.

## 🎮 Playing

Open the bot in Telegram and send `/start`. Tap **Play KiwiTap** to launch the Mini App.

Available bot commands:

| Command | Description |
| --- | --- |
| `/start` | Start the bot and open the game |
| `/balance` | Check your points |
| `/admin` | Show the admin-panel button to authorized admins |

The admin panel is available at `https://your-public-domain.example/admin`.

## ⚙️ Configuration

Gameplay settings, rewards, and feature availability can be adjusted through the admin panel. The default configuration is defined in `bot.py`; player and game data is stored in the local `game.db` SQLite database.

For local development only, `DEV=1` enables a development identity for requests opened outside Telegram. Do not enable this mode on a publicly accessible deployment.

## 📁 Project Layout

```text
.
├── assets/
│   └── ...                 # Bot welcome image
├── templates/
│   ├── index.html          # Player Mini App
│   └── admin.html          # Admin dashboard
├── bot.py                  # Telegram bot, Flask API, and game logic
└── game.db                 # Created and updated at runtime
```

## 🔐 Before Publishing or Deploying

- Never put bot tokens, admin keys, or other credentials in source control. Configure them as environment variables or deployment secrets.
- If a bot token has ever been included in a public or shared copy of the code, revoke it with BotFather and create a new one.
- Keep `game.db` private; it contains runtime player data.
- Use HTTPS for the Telegram Mini App and keep `DEV` disabled in production.

