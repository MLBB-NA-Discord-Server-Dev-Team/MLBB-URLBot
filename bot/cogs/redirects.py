"""
Redirects Cog — manage mlbb.site/NA/ redirect pages
"""
import logging
import os
import shutil
import re
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "templates")


def has_admin_role(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    member_roles = [r.name for r in interaction.user.roles]
    return any(role in member_roles for role in config.ADMIN_ROLES)


def admin_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not has_admin_role(interaction):
            await interaction.response.send_message(
                "❌ You need the **admins** role to use this command.", ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)


class Redirects(commands.Cog):
    """Manage mlbb.site/NA/ redirect pages"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    redirect = app_commands.Group(name="redirect", description="Manage URL redirects")

    @redirect.command(name="list", description="List all active redirects")
    @admin_check()
    async def redirect_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        base = config.NA_BASE_PATH
        try:
            entries = sorted([
                d for d in os.listdir(base)
                if os.path.isdir(os.path.join(base, d)) and not d.startswith('.')
            ])
        except Exception as e:
            await interaction.followup.send(f"❌ Error reading redirects: {e}", ephemeral=True)
            return

        if not entries:
            await interaction.followup.send("No redirects found.", ephemeral=True)
            return

        lines = []
        for slug in entries:
            rtype, dest = self._read_redirect_info(slug)
            type_badge = "🔗" if rtype == "plain" else "📋" if rtype == "google_form" else "❓"
            lines.append(f"{type_badge} **{slug}** — {dest or 'unknown'}")

        embed = discord.Embed(
            title=f"Active Redirects ({len(entries)})",
            description="\n".join(lines),
            color=0x3A86FF
        )
        embed.set_footer(text=f"Base: {config.NA_BASE_URL}/")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @redirect.command(name="info", description="Show details about a redirect")
    @app_commands.describe(slug="The redirect slug (folder name)")
    @admin_check()
    async def redirect_info(self, interaction: discord.Interaction, slug: str):
        await interaction.response.defer(ephemeral=True)
        path = os.path.join(config.NA_BASE_PATH, slug)
        if not os.path.isdir(path):
            await interaction.followup.send(f"❌ Redirect `{slug}` not found.", ephemeral=True)
            return

        rtype, dest = self._read_redirect_info(slug)
        embed = discord.Embed(title=f"Redirect: {slug}", color=0x3A86FF)
        embed.add_field(name="URL", value=f"{config.NA_BASE_URL}/{slug}/", inline=False)
        embed.add_field(name="Type", value=rtype or "unknown", inline=True)
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
            # Write script.js
            script = f'var destination = "{destination}";\n\n' + open(os.path.join(tmpl_path, "script.js.tmpl")).read()
            self._write(os.path.join(dest_path, "script.js"), script)
            # Write index.html with title
            html = open(os.path.join(tmpl_path, "index.html.tmpl")).read().replace("{{TITLE}}", title)
            self._write(os.path.join(dest_path, "index.html"), html)
        except Exception as e:
            logger.error(f"Error creating plain redirect: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to create redirect: {e}", ephemeral=True)
            return

        embed = discord.Embed(title="✅ Redirect Created", color=0x2ECC71)
        embed.add_field(name="Slug", value=slug, inline=True)
        embed.add_field(name="Type", value="Plain", inline=True)
        embed.add_field(name="URL", value=f"{config.NA_BASE_URL}/{slug}/", inline=False)
        embed.add_field(name="Destination", value=destination, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Created plain redirect: {slug} → {destination} by {interaction.user}")

    @redirect.command(name="create-form", description="Create a Google Form redirect with Discord identity pre-fill")
    @app_commands.describe(
        slug="URL slug (e.g. player-survey → mlbb.site/NA/player-survey/)",
        title="Page title shown during redirect",
        form_url="Google Form base URL (without pre-fill params)",
        discord_id_field="Google Form entry ID for Discord ID field (e.g. 744072366)",
        username_field="Google Form entry ID for Discord username field (e.g. 401452227)"
    )
    @admin_check()
    async def redirect_create_form(
        self,
        interaction: discord.Interaction,
        slug: str,
        title: str,
        form_url: str,
        discord_id_field: str,
        username_field: str
    ):
        await interaction.response.defer(ephemeral=True)
        slug = self._sanitize_slug(slug)
        err = self._validate_new_slug(slug)
        if err:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)
            return

        dest_path = os.path.join(config.NA_BASE_PATH, slug)
        tmpl_path = os.path.join(TEMPLATES_DIR, "google_form")
        redirect_uri = f"{config.NA_BASE_URL}/{slug}"
        auth_url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={config.REDIRECT_DISCORD_CLIENT_ID}"
            f"&redirect_uri={self._url_encode(redirect_uri)}"
            f"&response_type=token&scope=identify"
        )

        try:
            shutil.copytree(tmpl_path, dest_path)
            script = (
                open(os.path.join(tmpl_path, "script.js.tmpl")).read()
                .replace("{{AUTH_URL}}", auth_url)
                .replace("{{BASE_URL}}", form_url)
                .replace("{{UID_FIELD}}", discord_id_field)
                .replace("{{USER_FIELD}}", username_field)
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

        embed = discord.Embed(title="✅ Form Redirect Created", color=0x2ECC71)
        embed.add_field(name="Slug", value=slug, inline=True)
        embed.add_field(name="Type", value="Google Form", inline=True)
        embed.add_field(name="URL", value=f"{config.NA_BASE_URL}/{slug}/", inline=False)
        embed.add_field(name="Form", value=form_url, inline=False)
        embed.add_field(name="Discord ID Field", value=f"entry.{discord_id_field}", inline=True)
        embed.add_field(name="Username Field", value=f"entry.{username_field}", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Created form redirect: {slug} → {form_url} by {interaction.user}")

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
        path = os.path.join(config.NA_BASE_PATH, slug)
        if os.path.exists(path):
            return f"Redirect `{slug}` already exists."
        return None

    def _write(self, path: str, content: str):
        with open(path, 'w') as f:
            f.write(content)

    def _url_encode(self, url: str) -> str:
        from urllib.parse import quote
        return quote(url, safe='')

    def _read_redirect_info(self, slug: str):
        """Returns (type, destination) by reading script.js"""
        script_path = os.path.join(config.NA_BASE_PATH, slug, "script.js")
        if not os.path.exists(script_path):
            return (None, None)
        content = open(script_path).read()
        # plain redirect
        m = re.search(r'var destination\s*=\s*"([^"]+)"', content)
        if m:
            return ("plain", m.group(1))
        # google form redirect
        m = re.search(r'baseurl\s*=\s*"([^"]+)"', content)
        if m:
            return ("google_form", m.group(1))
        return (None, None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Redirects(bot))
