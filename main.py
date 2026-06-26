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
        self._connecting = False

    async def _ensure_lavalink(self):
        """Make sure at least one node CONNECTED. Wait or fresh-connect only."""
        # If pool has nodes, just poll for CONNECTED — no reconnect
        pool_nodes = list(wavelink.Pool.nodes)
        if pool_nodes:
            for n in pool_nodes:
                if n.status == wavelink.NodeStatus.CONNECTED:
                    return True
            # Wait up to 30s for async connection to complete
            for _ in range(30):
                await asyncio.sleep(1)
                for n in pool_nodes:
                    if n.status == wavelink.NodeStatus.CONNECTED:
                        return True
            # Still not connected — try reconnect via Pool.reconnect
            print("Lavalink node in pool but not CONNECTED — trying reconnect")
            try:
                await asyncio.wait_for(
                    wavelink.Pool.reconnect(client=self), timeout=20)
                for _ in range(15):
                    await asyncio.sleep(1)
                    for n in wavelink.Pool.nodes:
                        if n.status == wavelink.NodeStatus.CONNECTED:
                            print(f"Lavalink reconnected: {LAVALINK_URI}")
                            return True
            except Exception as e:
                print(f"Lavalink reconnect failed: {e}")
            return False

        # Pool empty — fresh connect
        if self._connecting:
            for _ in range(30):
                await asyncio.sleep(1)
                for n in wavelink.Pool.nodes:
                    if n.status == wavelink.NodeStatus.CONNECTED:
                        return True
            return False

        self._connecting = True
        node = wavelink.Node(uri=f"ws://{LAVALINK_URI}", password=LAVALINK_PASSWORD)
        for i in range(3):
            try:
                await asyncio.wait_for(
                    wavelink.Pool.connect(nodes=[node], client=self), timeout=20)
                for _ in range(15):
                    await asyncio.sleep(1)
                    for n in wavelink.Pool.nodes:
                        if n.status == wavelink.NodeStatus.CONNECTED:
                            self._connecting = False
                            print(f"Lavalink connected: {LAVALINK_URI}")
                            return True
                self._connecting = False
                return any(n.status == wavelink.NodeStatus.CONNECTED
                          for n in wavelink.Pool.nodes)
            except asyncio.TimeoutError:
                print(f"Lavalink timeout ({i+1}/3)")
            except Exception as e:
                print(f"Lavalink error ({i+1}/3): {e}")
            await asyncio.sleep(3)
        self._connecting = False
        print("Lavalink failed after 3 attempts")
        return False

    async def setup_hook(self):
        await self.load_extension('cogs.music')
        print("Loaded: cogs.music")
        await self.tree.sync()
        print("Synced slash commands.")


bot = CachyBot()


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    asyncio.create_task(bot._ensure_lavalink())


@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    print(f"Lavalink node ready: {payload.node}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Error: {error}")
    await ctx.send(f"Error: {error}")


if __name__ == "__main__":
    if not TOKEN:
        print("No DISCORD_TOKEN")
    else:
        bot.run(TOKEN)
