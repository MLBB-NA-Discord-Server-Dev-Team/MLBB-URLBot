# MLBB-URLBot

Discord bot for managing URL redirects on `mlbb.site/NA/`. Allows admins to create, list, and delete redirect pages — including Google Form redirects that pre-fill Discord identity fields via OAuth2.

## Commands

All commands require the `admins` role (configurable via `ADMIN_ROLES` in `.env`).

| Command | Description |
|---------|-------------|
| `/redirect list` | List all active redirects with type and destination |
| `/redirect info <slug>` | Show details for a specific redirect |
| `/redirect create-plain <slug> <title> <destination>` | Create a plain URL redirect |
| `/redirect create-form <slug> <title> <form_url> <discord_id_field> <username_field>` | Create a Google Form redirect with Discord identity pre-fill |
| `/redirect delete <slug>` | Delete a redirect |

### Plain redirect
Navigates the visitor directly to a destination URL after a short countdown.

```
URL: https://mlbb.site/NA/my-event/
→ Redirects to: https://example.com/signup
```

### Google Form redirect
Authenticates the visitor via Discord OAuth, then redirects to a Google Form with Discord ID and username pre-filled.

```
URL: https://mlbb.site/NA/player-survey/
→ Discord OAuth (identify)
→ https://docs.google.com/forms/d/.../viewform?usp=pp_url&entry.744072366=<discord_id>&entry.401452227=<username>
```

To find the entry IDs for your Google Form: open the form, right-click a field → Inspect, look for `entry.XXXXXXXXX` in the input `name` attribute.

## Setup

### 1. Two Discord Applications

This bot uses two separate Discord applications:

| App | Client ID | Purpose |
|-----|-----------|---------|
| **URLBot** | `1487660903112507525` | Bot presence, slash commands |
| **MLBB Auth** | `1073332119666966650` | OAuth2 identity flow on redirect pages |

The bot application (`1487660903112507525`) needs no special permissions — all slash command responses are ephemeral.

**Invite URL scopes:** `bot` + `applications.commands` (no permission bits required)

### 2. Discord OAuth redirect URIs

For each redirect slug you create, its URL must be added as an **Allowed Redirect URI** in the **MLBB Auth app** (`1073332119666966650`) **OAuth2** settings:
```
https://mlbb.site/NA/<slug>
```
This only needs to be done once per slug. The bot creates the page files automatically but cannot update the Developer Portal.

### 3. Configuration

Copy `.env.example` to `.env` — only `DISCORD_TOKEN` needs to be set, everything else is pre-configured:

```env
DISCORD_TOKEN=<bot token from application 1487660903112507525>
GUILD_IDS=850386581135163489
LOG_LEVEL=INFO

ADMIN_ROLES=admins

NA_BASE_PATH=/var/www/sites/mlbb.site/NA
NA_BASE_URL=https://mlbb.site/NA

REDIRECT_DISCORD_CLIENT_ID=1073332119666966650
```

### 4. Install dependencies

```bash
cd /root/MLBB-URLBot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Run (development)

```bash
cd /root/MLBB-URLBot
source venv/bin/activate
python run.py
```

### 6. Run (production — systemd)

```bash
sudo cp urlbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable urlbot.service
sudo systemctl start urlbot.service
sudo systemctl status urlbot.service
```

View logs:
```bash
sudo journalctl -u urlbot.service -f
```

## File Structure

```
MLBB-URLBot/
├── run.py
├── config.py
├── requirements.txt
├── .env / .env.example
├── urlbot.service              ← systemd unit file
│
├── bot/
│   ├── main.py
│   └── cogs/
│       └── redirects.py        ← all /redirect commands
│
└── templates/
    ├── plain/                  ← plain URL redirect template
    │   ├── index.html.tmpl
    │   ├── script.js.tmpl
    │   └── styles.css
    └── google_form/            ← Discord OAuth + Google Form template
        ├── index.html.tmpl
        ├── script.js.tmpl
        └── styles.css
```

## How Redirects Work

Each redirect is a folder under `NA_BASE_PATH` containing `index.html`, `script.js`, and `styles.css`. Apache serves these as static files. The bot creates and deletes these folders via the slash commands.

The redirect type is detected by reading `script.js`:
- **plain**: contains `var destination = "..."`
- **google_form**: contains `baseurl = "..."` (Discord OAuth flow)
