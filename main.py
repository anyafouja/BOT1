import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Bot setup
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
        # Explicitly load opus
        if not discord.opus.is_loaded():
            for lib in ('libopus.so.0', 'libopus.so', 'libopus0.so', 'libopus.so.0.11.1'):
                try:
                    discord.opus.load_opus(lib)
                    print(f"Loaded opus: {lib}")
                    break
                except Exception:
                    continue
            else:
                print("Failed to load libopus - voice may not work")

        # Load cogs
        try:
            await self.load_extension('cogs.music')
            print("Loaded extension: cogs.music")
        except Exception as e:
            print(f"Failed to load extension: {e}")

        # Sync slash commands
        await self.tree.sync()
        print("Synced slash commands.")

bot = CachyBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('------')

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
