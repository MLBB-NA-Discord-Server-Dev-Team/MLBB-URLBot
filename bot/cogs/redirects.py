"""
Redirects Cog — manage mlbb.site/NA/ redirect pages
"""
import logging
import os
import shutil
import re
from typing import Optional, List, Tuple
from urllib.parse import urlparse, quote
import discord
from discord import app_commands
from discord.ext import commands
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "templates")
PER_PAGE = 10


def has_admin_role(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    member_roles = [r.name for r in interaction.user.roles]
    return any(role in member_roles for role in config.ADMIN_ROLES)


def admin_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not has_admin_role(interaction):
            await interaction.response.send_message(
                "❌ You need an authorized role to use this command.", ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)


def _dest_host(url: str) -> str:
    """Return just the hostname of a URL for abbreviated display."""
    if not url:
        return "unknown"
    try:
        host = urlparse(url).netloc
        return host if host else url
    except Exception:
        return url


def _build_list_embed(entries: List[Tuple[str, str, str]], page: int, total_pages: int) -> discord.Embed:
    start = page * PER_PAGE
    chunk = entries[start:start + PER_PAGE]
    lines = []
    for slug, rtype, dest in chunk:
        url = f"{config.NA_BASE_URL}/{slug}/"
        badge = "🔗" if rtype == "plain" else "📋" if rtype == "google_form" else "❓"
        host = _dest_host(dest)
        lines.append(f"{badge} {url}  →  {host}")

    embed = discord.Embed(
        title=f"Active Redirects ({len(entries)})",
        description="\n".join(lines) if lines else "No redirects on this page.",
        color=0x3A86FF
    )
    embed.set_footer(text=f"Page {page + 1} of {total_pages}  •  🔗 plain  📋 google form")
    return embed


class RedirectListView(discord.ui.View):
    def __init__(self, entries: List[Tuple[str, str, str]]):
        super().__init__(timeout=120)
        self.entries = entries
        self.page = 0
        self.total_pages = max(1, (len(entries) + PER_PAGE - 1) // PER_PAGE)
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(
            embed=_build_list_embed(self.entries, self.page, self.total_pages), view=self
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(
            embed=_build_list_embed(self.entries, self.page, self.total_pages), view=self
        )


class Redirects(commands.Cog):
    """Manage mlbb.site/NA/ redirect pages"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    redirect = app_commands.Group(name="redirect", description="Manage URL redirects")

    @redirect.command(name="list", description="List all active redirects")
    @admin_check()
    async def redirect_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            slugs = sorted([
                d for d in os.listdir(config.NA_BASE_PATH)
                if os.path.isdir(os.path.join(config.NA_BASE_PATH, d)) and not d.startswith('.')
            ])
        except Exception as e:
            await interaction.followup.send(f"❌ Error reading redirects: {e}", ephemeral=True)
            return

        if not slugs:
            await interaction.followup.send("No redirects found.", ephemeral=True)
            return

        entries = [(slug, *self._read_redirect_info(slug)) for slug in slugs]
        total_pages = max(1, (len(entries) + PER_PAGE - 1) // PER_PAGE)
        view = RedirectListView(entries) if total_pages > 1 else None
        embed = _build_list_embed(entries, 0, total_pages)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @redirect.command(name="details", description="Show full source and destination for a redirect")
    @app_commands.describe(slug="The redirect slug (folder name)")
    @admin_check()
    async def redirect_details(self, interaction: discord.Interaction, slug: str):
        await interaction.response.defer(ephemeral=True)
        path = os.path.join(config.NA_BASE_PATH, slug)
        if not os.path.isdir(path):
            await interaction.followup.send(f"❌ Redirect `{slug}` not found.", ephemeral=True)
            return

        rtype, dest = self._read_redirect_info(slug)
        source_url = f"{config.NA_BASE_URL}/{slug}/"
        badge = "🔗 Plain" if rtype == "plain" else "📋 Google Form" if rtype == "google_form" else "❓ Unknown"

        embed = discord.Embed(title=f"Redirect: {slug}", color=0x3A86FF)
        embed.add_field(name="Type", value=badge, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
        embed.add_field(name="Source", value=source_url, inline=False)
        embed.add_field(name="Destination", value=dest or "unknown", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @redirect.command(name="create-plain", description="Create a plain URL redirect")
    @app_commands.describe(
        slug="URL slug (e.g. my-event → mlbb.site/NA/my-event/)",
        title="Page title shown during redirect",
        destination="Destination URL to redirect to"
    )
    @admin_check()
    async def redirect_create_plain(
        self,
        interaction: discord.Interaction,
        slug: str,
        title: str,
        destination: str
    ):
        await interaction.response.defer(ephemeral=True)
        slug = self._sanitize_slug(slug)
        err = self._validate_new_slug(slug)
        if err:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)
            return

        dest_path = os.path.join(config.NA_BASE_PATH, slug)
        tmpl_path = os.path.join(TEMPLATES_DIR, "plain")

        try:
            shutil.copytree(tmpl_path, dest_path)
            script = f'var destination = "{destination}";\n\n' + open(os.path.join(tmpl_path, "script.js.tmpl")).read()
            self._write(os.path.join(dest_path, "script.js"), script)
            html = open(os.path.join(tmpl_path, "index.html.tmpl")).read().replace("{{TITLE}}", title)
            self._write(os.path.join(dest_path, "index.html"), html)
        except Exception as e:
            logger.error(f"Error creating plain redirect: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to create redirect: {e}", ephemeral=True)
            return

        source_url = f"{config.NA_BASE_URL}/{slug}/"
        embed = discord.Embed(title="✅ Redirect Created", color=0x2ECC71)
        embed.add_field(name="Type", value="🔗 Plain", inline=True)
        embed.add_field(name="Source", value=source_url, inline=False)
        embed.add_field(name="Destination", value=destination, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Created plain redirect: {slug} → {destination} by {interaction.user}")

    @redirect.command(name="create-form", description="Create a Google Form redirect with Discord identity pre-fill")
    @app_commands.describe(
        slug="URL slug (e.g. player-survey → mlbb.site/NA/player-survey/)",
        title="Page title shown during redirect",
        form_url="Full Google Form URL — paste the pre-filled link to auto-extract entry field IDs",
        discord_id_field="entry field ID for Discord ID (auto-extracted if present in URL)",
        username_field="entry field ID for Discord username (auto-extracted if present in URL)"
    )
    @admin_check()
    async def redirect_create_form(
        self,
        interaction: discord.Interaction,
        slug: str,
        title: str,
        form_url: str,
        discord_id_field: Optional[str] = None,
        username_field: Optional[str] = None
    ):
        await interaction.response.defer(ephemeral=True)
        slug = self._sanitize_slug(slug)
        err = self._validate_new_slug(slug)
        if err:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)
            return

        # Parse the URL — strip entry.* params and extract field IDs
        base_url, extracted_fields = self._parse_form_url(form_url)

        # Override extracted with explicitly provided values
        if discord_id_field:
            extracted_fields[0] = discord_id_field.lstrip("entry.")
        if username_field:
            extracted_fields[1] = username_field.lstrip("entry.")

        id_field = extracted_fields.get(0)
        user_field = extracted_fields.get(1)

        if not id_field or not user_field:
            found = len(extracted_fields)
            await interaction.followup.send(
                f"❌ Could not determine both field IDs.\n"
                f"Found {found} `entry.*` param(s) in URL. "
                f"Please provide `discord_id_field` and `username_field` explicitly.",
                ephemeral=True
            )
            return

        dest_path = os.path.join(config.NA_BASE_PATH, slug)
        tmpl_path = os.path.join(TEMPLATES_DIR, "google_form")
        redirect_uri = f"{config.NA_BASE_URL}/{slug}"
        auth_url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={config.REDIRECT_DISCORD_CLIENT_ID}"
            f"&redirect_uri={quote(redirect_uri, safe='')}"
            f"&response_type=token&scope=identify"
        )

        try:
            shutil.copytree(tmpl_path, dest_path)
            script = (
                open(os.path.join(tmpl_path, "script.js.tmpl")).read()
                .replace("{{AUTH_URL}}", auth_url)
                .replace("{{BASE_URL}}", base_url)
                .replace("{{UID_FIELD}}", id_field)
                .replace("{{USER_FIELD}}", user_field)
            )
            self._write(os.path.join(dest_path, "script.js"), script)
            html = (
                open(os.path.join(tmpl_path, "index.html.tmpl")).read()
                .replace("{{TITLE}}", title)
                .replace("{{AUTH_URL}}", auth_url)
            )
            self._write(os.path.join(dest_path, "index.html"), html)
        except Exception as e:
            logger.error(f"Error creating form redirect: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to create redirect: {e}", ephemeral=True)
            return

        source_url = f"{config.NA_BASE_URL}/{slug}/"
        auto = " *(auto-extracted)*" if not discord_id_field and not username_field else ""
        embed = discord.Embed(title="✅ Form Redirect Created", color=0x2ECC71)
        embed.add_field(name="Type", value="📋 Google Form", inline=True)
        embed.add_field(name="Source", value=source_url, inline=False)
        embed.add_field(name="Destination", value=base_url, inline=False)
        embed.add_field(name="Discord ID Field", value=f"entry.{id_field}{auto}", inline=True)
        embed.add_field(name="Username Field", value=f"entry.{user_field}{auto}", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Created form redirect: {slug} → {base_url} (id={id_field} user={user_field}) by {interaction.user}")

    @redirect.command(name="delete", description="Delete a redirect")
    @app_commands.describe(slug="The redirect slug to delete")
    @admin_check()
    async def redirect_delete(self, interaction: discord.Interaction, slug: str):
        await interaction.response.defer(ephemeral=True)
        path = os.path.join(config.NA_BASE_PATH, slug)
        if not os.path.isdir(path):
            await interaction.followup.send(f"❌ Redirect `{slug}` not found.", ephemeral=True)
            return
        try:
            shutil.rmtree(path)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to delete: {e}", ephemeral=True)
            return
        await interaction.followup.send(f"✅ Redirect `{slug}` deleted.", ephemeral=True)
        logger.info(f"Deleted redirect: {slug} by {interaction.user}")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _sanitize_slug(self, slug: str) -> str:
        return re.sub(r'[^a-zA-Z0-9\-_]', '-', slug).strip('-')

    def _validate_new_slug(self, slug: str) -> Optional[str]:
        if not slug:
            return "Slug cannot be empty."
        if os.path.exists(os.path.join(config.NA_BASE_PATH, slug)):
            return f"Redirect `{slug}` already exists."
        return None

    def _write(self, path: str, content: str):
        with open(path, 'w') as f:
            f.write(content)

    def _parse_form_url(self, url: str) -> Tuple[str, dict]:
        """
        Split a (possibly pre-filled) Google Form URL into:
          - base_url: the form URL with entry.* params stripped
          - fields: {0: first_entry_id, 1: second_entry_id, ...} in order found
        """
        from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
        parsed = urlparse(url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        entry_ids = []
        clean_pairs = []
        for key, value in pairs:
            m = re.match(r'^entry\.(\d+)$', key)
            if m:
                entry_ids.append(m.group(1))
            else:
                clean_pairs.append((key, value))
        clean_query = urlencode(clean_pairs)
        base_url = urlunparse(parsed._replace(query=clean_query))
        fields = {i: entry_ids[i] for i in range(len(entry_ids))}
        return base_url, fields

    def _read_redirect_info(self, slug: str) -> Tuple[Optional[str], Optional[str]]:
        """Returns (type, destination) by reading script.js"""
        script_path = os.path.join(config.NA_BASE_PATH, slug, "script.js")
        if not os.path.exists(script_path):
            return (None, None)
        content = open(script_path).read()
        m = re.search(r'var destination\s*=\s*"([^"]+)"', content)
        if m:
            return ("plain", m.group(1))
        m = re.search(r'baseurl\s*=\s*"([^"]+)"', content)
        if m:
            return ("google_form", m.group(1))
        return (None, None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Redirects(bot))
