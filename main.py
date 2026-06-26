import asyncio
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import wavelink

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

LAVALINK_URI = os.getenv('LAVALINK_URI', 'lavalink.triniumhost.com:4333')
LAVALINK_PASSWORD = os.getenv('LAVALINK_PASSWORD', 'free')
LAVALINK_SECURE = os.getenv('LAVALINK_SECURE', 'false').lower() == 'true'

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True


class CachyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="cachy ",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        await self.load_extension('cogs.music')
        print("Loaded extension: cogs.music")

        nodes = [
            wavelink.Node(
                uri=f"ws://{LAVALINK_URI}",
                password=LAVALINK_PASSWORD,
            )
        ]
        try:
            await asyncio.wait_for(wavelink.Pool.connect(nodes=nodes, client=self), timeout=15)
            print(f"Connected to Lavalink: {LAVALINK_URI}")
        except asyncio.TimeoutError:
            print(f"Lavalink connection timeout (15s) to {LAVALINK_URI} — bot will retry on next play")
        except Exception as e:
            print(f"Lavalink connect failed: {e}")

        await self.tree.sync()
        print("Synced slash commands.")


bot = CachyBot()


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('------')


@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    print(f"Lavalink node ready: {payload.node}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Error: {error}")
    await ctx.send(f"An error occurred: {error}")


if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env file.")
    else:
        bot.run(TOKEN)
