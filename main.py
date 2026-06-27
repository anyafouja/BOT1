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

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True


class CachyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="cachy ",
                         intents=intents, help_command=None)
        self.lavalink_ready = asyncio.Event()
        self._connect_task = None

    async def setup_hook(self):
        await self.load_extension('cogs.music')
        print("Loaded: cogs.music")
        await self.tree.sync()
        print("Synced slash commands.")

    async def _connect_lavalink(self):
        """Fire-and-forget connect. on_wavelink_node_ready sets the event."""
        node = wavelink.Node(uri=f"ws://{LAVALINK_URI}", password=LAVALINK_PASSWORD)
        for i in range(3):
            try:
                await asyncio.wait_for(
                    wavelink.Pool.connect(nodes=[node], client=self), timeout=20)
                print(f"Lavalink connect sent: {LAVALINK_URI}")
                return
            except asyncio.TimeoutError:
                print(f"Lavalink timeout ({i+1}/3)")
            except Exception as e:
                print(f"Lavalink error ({i+1}/3): {e}")
            await asyncio.sleep(3)
        print("Lavalink failed after 3 attempts")

    async def ensure_node(self):
        """Wait up to 60s for node to be CONNECTED."""
        if self.lavalink_ready.is_set():
            return True
        try:
            await asyncio.wait_for(self.lavalink_ready.wait(), timeout=60)
            return True
        except asyncio.TimeoutError:
            # Try fresh connect if never succeeded
            if not self._connect_task or self._connect_task.done():
                self._connect_task = asyncio.create_task(self._connect_lavalink())
            try:
                await asyncio.wait_for(self.lavalink_ready.wait(), timeout=30)
                return True
            except asyncio.TimeoutError:
                return False


bot = CachyBot()


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    bot._connect_task = asyncio.create_task(bot._connect_lavalink())


@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    print(f"Lavalink node ready: {payload.node}")
    bot.lavalink_ready.set()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.HybridCommandError):
        error = error.original
    try:
        if ctx.interaction and ctx.interaction.response.is_done():
            await ctx.interaction.followup.send(f"Error: {error}", ephemeral=True)
        else:
            await ctx.send(f"Error: {error}")
    except Exception:
        pass
    print(f"Error: {error}")


if __name__ == "__main__":
    if not TOKEN:
        print("No DISCORD_TOKEN")
    else:
        bot.run(TOKEN)
