"""
Configuration for MLBB-URLBot
"""
import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
GUILD_IDS: List[int] = [int(g) for g in os.getenv("GUILD_IDS", "").split(",") if g.strip()]
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# Role allowed to manage redirects
ADMIN_ROLES: List[str] = [r.strip() for r in os.getenv("ADMIN_ROLES", "admins").split(",") if r.strip()]

# Filesystem base path for NA redirects
NA_BASE_PATH: str = os.getenv("NA_BASE_PATH", "/var/www/sites/mlbb.site/NA")
NA_BASE_URL: str = os.getenv("NA_BASE_URL", "https://mlbb.site/NA")

# Discord OAuth app for redirect pages (the client_id embedded in redirect HTML)
REDIRECT_DISCORD_CLIENT_ID: str = os.getenv("REDIRECT_DISCORD_CLIENT_ID", "1073332119666966650")

# Future: subdomain base paths
# e.g. SUBDOMAIN_PATHS = {"events": "/var/www/sites/events.mlbb.site", ...}

def validate():
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN is required")
