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

class PinkHelp(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        embed = discord.Embed(title="Cachy Music Help", color=0xFFC0CB)
        description = ""

        for cog, cmds in mapping.items():
            filtered = await self.filter_commands(cmds, sort=True)
            for command in filtered:
                description += f"**cachy {command.name}**\n{command.help or 'No description'}\n\n"

        embed.description = description
        embed.set_footer(text="Cachy Music Bot")

        channel = self.get_destination()
        await channel.send(embed=embed)

    async def send_command_help(self, command):
        embed = discord.Embed(title=f"Help: {command.name}", color=0xFFC0CB)
        embed.add_field(name="Usage", value=f"cachy {command.name} {command.signature}")
        embed.add_field(name="Description", value=command.help or "No description", inline=False)

        if command.aliases:
            embed.add_field(name="Aliases", value=", ".join(command.aliases), inline=False)

        channel = self.get_destination()
        await channel.send(embed=embed)

class CachyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="cachy ",
            intents=intents,
            help_command=PinkHelp()
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
