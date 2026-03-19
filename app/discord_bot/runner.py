from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from .config import DiscordBotConfig
from .services import BinanceDiscordService


_MESSAGE_LIMIT = 1900


def _chunks(text: str, *, limit: int = _MESSAGE_LIMIT) -> list[str]:
    text = text.strip() or "(empty)"
    if len(text) <= limit:
        return [text]
    lines = text.splitlines() or [text]
    parts: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}".strip() if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        if len(line) <= limit:
            current = line
            continue
        for idx in range(0, len(line), limit):
            parts.append(line[idx : idx + limit])
        current = ""
    if current:
        parts.append(current)
    return parts or [text[:limit]]


async def _send_long(interaction: discord.Interaction, text: str) -> None:
    parts = _chunks(text)
    await interaction.response.send_message(parts[0], ephemeral=True)
    for part in parts[1:]:
        await interaction.followup.send(part, ephemeral=True)


def build_bot(config: DiscordBotConfig, service: BinanceDiscordService) -> commands.Bot:
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents, application_id=config.application_id_int)

    @bot.event
    async def on_ready() -> None:
        activity = discord.Game(name=config.presence_text or "crypto goblin things")
        await bot.change_presence(activity=activity)
        guild_obj = discord.Object(id=config.guild_id_int) if config.guild_id_int else None
        if config.sync_commands:
            if guild_obj is not None:
                bot.tree.copy_global_to(guild=guild_obj)
                await bot.tree.sync(guild=guild_obj)
            else:
                await bot.tree.sync()
        print(f"Discord bot ready as {bot.user}", flush=True)

    @bot.tree.command(name="help", description="Show trading bot Discord commands")
    async def help_command(interaction: discord.Interaction) -> None:
        await _send_long(interaction, service.help_text())

    @bot.tree.command(name="status", description="Show local Binance bot runtime status")
    async def status_command(interaction: discord.Interaction) -> None:
        await _send_long(interaction, service.status_text())

    @bot.tree.command(name="outlook", description="Generate an outlook report for a market")
    @app_commands.describe(symbol="Optional pair like SOL/USDT")
    async def outlook_command(interaction: discord.Interaction, symbol: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        text = await asyncio.to_thread(service.generate_outlook_text, symbol)
        for idx, part in enumerate(_chunks(text)):
            if idx == 0:
                await interaction.followup.send(part, ephemeral=True)
            else:
                await interaction.followup.send(part, ephemeral=True)

    @bot.tree.command(name="scan", description="Run the existing market scan and show the report")
    @app_commands.describe(venue="binance or polymarket", top="How many ranked rows to print in the scan output")
    async def scan_command(interaction: discord.Interaction, venue: str = "binance", top: int = 5) -> None:
        venue = venue.strip().lower()
        if venue not in {"binance", "polymarket"}:
            await interaction.response.send_message("venue must be `binance` or `polymarket`", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        text = await asyncio.to_thread(service.scan_text, venue=venue, top=max(1, min(top, 20)))
        for part in _chunks(text):
            await interaction.followup.send(part, ephemeral=True)

    @bot.tree.command(name="readonly", description="Show the latest saved Binance live-readonly report")
    async def readonly_command(interaction: discord.Interaction) -> None:
        await _send_long(interaction, service.latest_readonly_text())

    @bot.tree.command(name="approve", description="Queue approve <ticket-or-symbol> into the manual command queue")
    async def approve_command(interaction: discord.Interaction, target: str) -> None:
        if not config.allow_manual_actions:
            await interaction.response.send_message("manual queue actions are disabled", ephemeral=True)
            return
        result = service.queue_command(
            command_text=f"approve {target}",
            actor_id=str(interaction.user.id),
            actor_label=interaction.user.display_name,
        )
        await interaction.response.send_message(
            f"Queued `{result.command_text}` as `{result.command_id}` from `{result.actor_label}`",
            ephemeral=True,
        )

    @bot.tree.command(name="deny", description="Queue deny <ticket-or-symbol> into the manual command queue")
    async def deny_command(interaction: discord.Interaction, target: str) -> None:
        if not config.allow_manual_actions:
            await interaction.response.send_message("manual queue actions are disabled", ephemeral=True)
            return
        result = service.queue_command(
            command_text=f"deny {target}",
            actor_id=str(interaction.user.id),
            actor_label=interaction.user.display_name,
        )
        await interaction.response.send_message(
            f"Queued `{result.command_text}` as `{result.command_id}` from `{result.actor_label}`",
            ephemeral=True,
        )

    @bot.tree.command(name="confirm_sell", description="Queue confirm sell <asset> into the manual command queue")
    async def confirm_sell_command(interaction: discord.Interaction, asset: str) -> None:
        if not config.allow_manual_actions:
            await interaction.response.send_message("manual queue actions are disabled", ephemeral=True)
            return
        normalized = asset.strip().lower()
        if not normalized:
            await interaction.response.send_message("asset is required", ephemeral=True)
            return
        result = service.queue_command(
            command_text=f"confirm sell {normalized}",
            actor_id=str(interaction.user.id),
            actor_label=interaction.user.display_name,
        )
        await interaction.response.send_message(
            f"Queued `{result.command_text}` as `{result.command_id}` from `{result.actor_label}`",
            ephemeral=True,
        )

    return bot


def run_discord_bot(config: DiscordBotConfig | None = None, service: BinanceDiscordService | None = None) -> None:
    resolved_config = config or DiscordBotConfig()
    resolved_config.validate()
    resolved_service = service or BinanceDiscordService()
    bot = build_bot(resolved_config, resolved_service)
    bot.run(resolved_config.token)
