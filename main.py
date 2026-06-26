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
        """Make sure at least one node CONNECTED. Safe reconnect or connect."""
        # Pool.nodes may contain string IDs — filter to real Node objects
        def real_nodes():
            return [n for n in wavelink.Pool.nodes if isinstance(n, wavelink.Node)]

        nodes = real_nodes()
        for n in nodes:
            if n.status == wavelink.NodeStatus.CONNECTED:
                return True

        # Consolidate connect attempt
        if self._connecting:
            for _ in range(30):
                await asyncio.sleep(1)
                for n in real_nodes():
                    if n.status == wavelink.NodeStatus.CONNECTED:
                        return True
            return False

        self._connecting = True

        # If pool has real nodes, use Pool.reconnect
        if nodes:
            for i in range(3):
                try:
                    await asyncio.wait_for(
                        wavelink.Pool.reconnect(client=self), timeout=20)
                    for _ in range(15):
                        await asyncio.sleep(1)
                        for n in real_nodes():
                            if n.status == wavelink.NodeStatus.CONNECTED:
                                self._connecting = False
                                return True
                except Exception as e:
                    print(f"Lavalink reconnect err ({i+1}/3): {e}")
                await asyncio.sleep(3)
            self._connecting = False
            return False

        # Pool has only string IDs or empty — fresh connect
        for i in range(3):
            node = wavelink.Node(uri=f"ws://{LAVALINK_URI}", password=LAVALINK_PASSWORD)
            try:
                await asyncio.wait_for(
                    wavelink.Pool.connect(nodes=[node], client=self), timeout=20)
                for _ in range(15):
                    await asyncio.sleep(1)
                    for n in real_nodes():
                        if n.status == wavelink.NodeStatus.CONNECTED:
                            self._connecting = False
                            return True
                # connect returned but node not CONNECTED yet — give up
                self._connecting = False
                return any(n.status == wavelink.NodeStatus.CONNECTED
                          for n in real_nodes())
            except asyncio.TimeoutError:
                print(f"Lavalink timeout ({i+1}/3)")
            except Exception as e:
                print(f"Lavalink error ({i+1}/3): {e}")
            await asyncio.sleep(3)
        self._connecting = False
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
    # Don't send on already-acked interactions
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
