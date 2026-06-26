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


class CachyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="cachy ",
                         intents=intents, help_command=None)
        self._connecting = False

    async def setup_hook(self):
        await self.load_extension('cogs.music')
        print("Loaded: cogs.music")
        await self.tree.sync()
        print("Synced slash commands.")

    async def _connect_lavalink(self):
        if self._connecting:
            return
        self._connecting = True
        nodes = [wavelink.Node(uri=f"ws://{LAVALINK_URI}",
                               password=LAVALINK_PASSWORD)]
        for i in range(3):
            try:
                await asyncio.wait_for(
                    wavelink.Pool.connect(nodes=nodes, client=self), timeout=20)
                print(f"Lavalink OK: {LAVALINK_URI}")
                return
            except asyncio.TimeoutError:
                print(f"Lavalink timeout ({i+1}/3)")
            except Exception as e:
                print(f"Lavalink error ({i+1}/3): {e}")
            await asyncio.sleep(3)
        self._connecting = False
        print("Lavalink failed — will retry on play command.")

    async def ensure_node(self):
        ok = any(n.status == wavelink.NodeStatus.CONNECTED
                 for n in wavelink.Pool.nodes)
        if ok:
            return True
        self._connecting = False
        try:
            await asyncio.wait_for(self._connect_lavalink(), timeout=70)
            return any(n.status == wavelink.NodeStatus.CONNECTED
                       for n in wavelink.Pool.nodes)
        except Exception:
            return False


bot = CachyBot()


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    asyncio.create_task(bot._connect_lavalink())


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
