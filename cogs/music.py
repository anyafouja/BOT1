import asyncio
import discord
import random
import itertools
from discord.ext import commands
import wavelink


FFMPEG_OPTIONS = {
    'before_options': (
        '-reconnect 1 '
        '-reconnect_streamed 1 '
        '-reconnect_delay_max 5 '
        '-reconnect_on_network_error 1 '
    ),
    'options': '-vn',
}


class MusicPlayer:
    __slots__ = (
        'bot', '_guild', '_channel', '_cog',
        'queue', 'current', 'np', 'volume',
        'loop', '_stop', '_next_up', 'history',
        '_task', '_finished',
    )

    def __init__(self, ctx):
        self.bot = ctx.bot
        self._guild = ctx.guild
        self._channel = ctx.channel
        self._cog = ctx.cog

        self.queue = asyncio.Queue()
        self.np = None
        self.volume = 0.5
        self.current = None
        self.loop = False
        self._stop = False
        self._next_up = None
        self.history = []

        self._finished = asyncio.Event()
        self._task = ctx.bot.loop.create_task(self.player_loop())

    def _after_playing(self, error):
        if error:
            print(f'[MusicPlayer] Playback error: {error}')
        self.bot.loop.call_soon_threadsafe(self._finished.set)

    async def player_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self._stop = False
            self._finished.clear()

            try:
                if self._next_up:
                    item = self._next_up
                    self._next_up = None
                elif self.loop and self.current:
                    item = self.current
                else:
                    item = await asyncio.wait_for(self.queue.get(), timeout=300)
            except asyncio.TimeoutError:
                await self._cog.cleanup(self._guild)
                return
            except asyncio.CancelledError:
                return

            # item is a wavelink.Playable when from queue
            track = item

            vc = self._guild.voice_client
            if not vc or not isinstance(vc, wavelink.Player):
                await self._channel.send('Lost connection to voice channel.')
                await self._cog.cleanup(self._guild)
                return

            try:
                await vc.play(track)
            except Exception as e:
                await self._channel.send(f'Error starting playback: `{e}`')
                self.current = None
                continue

            self.current = track

            view = NowPlayingView(self, self._guild.id)

            try:
                embed = discord.Embed(
                    title=track.title[:256],
                    color=0xFFC0CB,
                )
                if track.artwork:
                    embed.set_thumbnail(url=track.artwork)
                embed.add_field(name='Channel', value=track.author or 'Unknown')
                embed.add_field(name='Duration', value=_format_duration(track.length))
                if self.np:
                    try:
                        await self.np.delete()
                    except Exception:
                        pass
                self.np = await self._channel.send(embed=embed, view=view)
            except Exception:
                pass

            # Wait for playback to finish (poll every 5s)
            try:
                while vc.playing or vc.paused:
                    await asyncio.sleep(2)
                    if self._stop:
                        await vc.stop()
                        break
            except Exception:
                pass

            if not self._stop and self.current:
                self.history.append(self.current)
                if len(self.history) > 20:
                    self.history.pop(0)

            if not self.loop:
                self.current = None

            if not self.current and self.queue.empty():
                if self.np:
                    try:
                        await self.np.delete()
                    except Exception:
                        pass
                self.np = None


class NowPlayingView(discord.ui.View):
    def __init__(self, player, guild_id):
        super().__init__(timeout=None)
        self.player = player
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message('Not for this server.', ephemeral=True)
            return False
        vc = interaction.guild.voice_client
        if not vc or not vc.channel:
            await interaction.response.send_message('Not connected to voice.', ephemeral=True)
            return False
        if interaction.user not in vc.channel.members:
            await interaction.response.send_message('Join the voice channel first.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='\u25C1\u25C1', style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        if not player.current:
            return await interaction.response.send_message('Nothing playing.', ephemeral=True)
        if not player.history:
            return await interaction.response.send_message('No previous song.', ephemeral=True)
        player._next_up = player.history.pop()
        player._stop = True
        vc = interaction.guild.voice_client
        if vc:
            await vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label='||', style=discord.ButtonStyle.secondary)
    async def pause_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc or not isinstance(vc, wavelink.Player):
            return await interaction.response.send_message('Not connected.', ephemeral=True)
        if vc.paused:
            await vc.pause(False)
            button.label = '||'
        elif vc.playing:
            await vc.pause(True)
            button.label = '\u25B7'
        else:
            return await interaction.response.send_message('Nothing playing.', ephemeral=True)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label='\u25B7\u25B7', style=discord.ButtonStyle.secondary)
    async def next_(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        if not player.current:
            return await interaction.response.send_message('Nothing playing.', ephemeral=True)
        player._stop = True
        vc = interaction.guild.voice_client
        if vc:
            await vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label='\u27F3', style=discord.ButtonStyle.secondary)
    async def loop_(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        player.loop = not player.loop
        button.label = '\u27F2' if player.loop else '\u27F3'
        await interaction.response.edit_message(view=self)


def _format_duration(ms: int) -> str:
    seconds = ms // 1000
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}h {minutes}m {sec}s'
    return f'{minutes}m {sec}s'


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}
        self.locks = {}

    async def cleanup(self, guild):
        try:
            player = self.players.get(guild.id)
            if player:
                player._stop = True
                if player.np:
                    try:
                        await player.np.delete()
                    except Exception:
                        pass
                    player.np = None
                if player._task and not player._task.done():
                    player._task.cancel()
        except Exception:
            pass
        try:
            vc = guild.voice_client
            if vc:
                await vc.disconnect(force=True)
        except Exception:
            pass
        self.players.pop(guild.id, None)
        self.locks.pop(guild.id, None)

    async def get_player(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.locks:
            self.locks[guild_id] = asyncio.Lock()
        async with self.locks[guild_id]:
            if guild_id not in self.players:
                self.players[guild_id] = MusicPlayer(ctx)
            return self.players[guild_id]

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id == self.bot.user.id:
            if after.channel is None:
                await self.cleanup(member.guild)
            return
        vc = member.guild.voice_client
        if vc and vc.channel and len([m for m in vc.channel.members if not m.bot]) == 0:
            await asyncio.sleep(60)
            vc = member.guild.voice_client
            if vc and vc.channel and len([m for m in vc.channel.members if not m.bot]) == 0:
                await self.cleanup(member.guild)

    async def _ensure_voice(self, ctx) -> bool:
        vc = ctx.voice_client
        if not vc or not isinstance(vc, wavelink.Player):
            if ctx.author.voice:
                try:
                    await ctx.author.voice.channel.edit(rtc_region='singapore')
                except Exception:
                    pass
                vc = await ctx.author.voice.channel.connect(cls=wavelink.Player, reconnect=True)
            else:
                await ctx.send('You are not connected to a voice channel.')
                return False
        elif ctx.author.voice and vc.channel != ctx.author.voice.channel:
            await vc.move_to(ctx.author.voice.channel)
        return True

    @commands.hybrid_command(name='play', aliases=['p'])
    async def play_(self, ctx, *, search: str):
        """Plays a song from YouTube or SoundCloud."""
        if not await self._ensure_voice(ctx):
            return

        vc = ctx.voice_client

        async with ctx.typing():
            try:
                tracks = await wavelink.Playable.search(
                    search,
                    source=wavelink.TrackSource.YouTube,
                )
                if not tracks:
                    # Fallback to SoundCloud
                    tracks = await wavelink.Playable.search(
                        search,
                        source=wavelink.TrackSource.SC,
                    )
                if not tracks:
                    return await ctx.send('No results found.')

                track = tracks if isinstance(tracks, wavelink.Playlist) else tracks[0]

            except Exception as e:
                return await ctx.send(f'Search failed: `{e}`')

        player = await self.get_player(ctx)

        if isinstance(track, wavelink.Playlist):
            for t in track.tracks:
                await player.queue.put(t)
            embed = discord.Embed(title='Added Playlist', color=0xFFC0CB)
            embed.description = f'[{track.name}]({track.url}) — {len(track.tracks)} tracks'
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)
        else:
            await player.queue.put(track)
            embed = discord.Embed(title='Added to Queue', color=0xFFC0CB)
            embed.description = f'[{track.title}]({track.uri})'
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='skip', aliases=['s'])
    async def skip_(self, ctx):
        """Skips the current song."""
        vc = ctx.voice_client
        if not vc or not (getattr(vc, 'playing', False) or getattr(vc, 'paused', False)):
            return await ctx.send('Nothing is playing.')
        player = await self.get_player(ctx)
        player._stop = True
        await vc.stop()
        player.current = None
        await ctx.send(embed=discord.Embed(description='Skipped', color=0xFFC0CB))

    @commands.hybrid_command(name='stop')
    async def stop_(self, ctx):
        """Stops playback and disconnects the bot."""
        vc = ctx.voice_client
        if not vc or not vc.connected:
            return await ctx.send('Not connected.')
        await self.cleanup(ctx.guild)
        await ctx.send(embed=discord.Embed(description='Stopped', color=0xFFC0CB))

    @commands.hybrid_command(name='pause')
    async def pause_(self, ctx):
        """Pauses the music."""
        vc = ctx.voice_client
        if not vc or not isinstance(vc, wavelink.Player):
            return await ctx.send('Not connected to Lavalink.')
        if vc.playing:
            await vc.pause(True)
            await ctx.send(embed=discord.Embed(description='Paused', color=0xFFC0CB))
        else:
            await ctx.send('Nothing is playing.')

    @commands.hybrid_command(name='resume')
    async def resume_(self, ctx):
        """Resumes the paused music."""
        vc = ctx.voice_client
        if not vc or not isinstance(vc, wavelink.Player):
            return await ctx.send('Not connected.')
        if vc.paused:
            await vc.pause(False)
            await ctx.send(embed=discord.Embed(description='Resumed', color=0xFFC0CB))
        else:
            await ctx.send('Not paused.')

    @commands.hybrid_command(name='queue', aliases=['q'])
    async def queue_info(self, ctx):
        """Shows the current song queue."""
        player = await self.get_player(ctx)
        if player.queue.empty():
            return await ctx.send('Queue is empty.')
        upcoming = list(itertools.islice(player.queue._queue, 0, 10))
        fmt = '\n'.join(
            f"**{i+1}.** {item.title}" for i, item in enumerate(upcoming)
        )
        await ctx.send(embed=discord.Embed(title='Queue', description=fmt, color=0xFFC0CB))

    @commands.hybrid_command(name='volume', aliases=['vol'])
    async def change_volume(self, ctx, vol: int):
        """Changes the bot volume (1-100)."""
        vc = ctx.voice_client
        if not vc or not isinstance(vc, wavelink.Player):
            return await ctx.send('Not connected.')
        if not 0 < vol <= 100:
            return await ctx.send('Invalid volume (1-100).')
        await vc.set_volume(vol)
        player = await self.get_player(ctx)
        player.volume = vol / 100
        await ctx.send(embed=discord.Embed(description=f'Volume: {vol}%', color=0xFFC0CB))

    @commands.hybrid_command(name='nowplaying', aliases=['np'])
    async def nowplaying_(self, ctx):
        """Shows the currently playing track."""
        vc = ctx.voice_client
        if not vc or not isinstance(vc, wavelink.Player) or not vc.playing:
            return await ctx.send('Nothing is playing.')
        track = vc.current
        embed = discord.Embed(
            title=track.title[:256],
            url=track.uri,
            color=0xFFC0CB,
        )
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
        embed.add_field(name='Channel', value=track.author or 'Unknown')
        embed.add_field(name='Duration', value=_format_duration(track.length))
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='help')
    async def help_(self, ctx):
        """Shows all commands."""
        cmds = [
            ('play <query>', 'Search & play from YouTube / SoundCloud via Lavalink'),
            ('skip', 'Skips the current song'),
            ('stop', 'Stops playback and disconnects'),
            ('pause', 'Pauses playback'),
            ('resume', 'Resumes playback'),
            ('volume <1-100>', 'Sets the volume'),
            ('queue', 'Shows the song queue'),
            ('nowplaying', 'Shows the current track info'),
            ('clear-queue', 'Clears all queued songs'),
            ('shuffle', 'Shuffles the queue'),
            ('loop', 'Toggles loop mode'),
            ('ping', 'Checks bot latency'),
        ]
        embed = discord.Embed(title='Cachy Music', color=0xFFC0CB)
        embed.description = '\n\n'.join(f'**cachy {cmd}**\n{desc}' for cmd, desc in cmds)
        embed.set_footer(text='Powered by Lavalink | YouTube + SoundCloud')
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='ping')
    async def ping_(self, ctx):
        """Checks the bot latency."""
        await ctx.send(embed=discord.Embed(
            description=f'Pong! {round(self.bot.latency * 1000)}ms',
            color=0xFFC0CB,
        ))

    @commands.hybrid_command(name='clear-queue')
    async def clear_queue_(self, ctx):
        """Clears all songs from the queue."""
        player = await self.get_player(ctx)
        while not player.queue.empty():
            try:
                player.queue.get_nowait()
            except Exception:
                break
        await ctx.send(embed=discord.Embed(description='Queue cleared', color=0xFFC0CB))

    @commands.hybrid_command(name='loop')
    async def loop_(self, ctx):
        """Toggles looping of the current song."""
        player = await self.get_player(ctx)
        player.loop = not player.loop
        await ctx.send(embed=discord.Embed(
            description=f'Loop {"on" if player.loop else "off"}',
            color=0xFFC0CB,
        ))

    @commands.hybrid_command(name='shuffle')
    async def shuffle_(self, ctx):
        """Shuffles the songs in the queue."""
        player = await self.get_player(ctx)
        if player.queue.empty():
            return await ctx.send('Queue is empty.')
        songs = []
        while not player.queue.empty():
            try:
                songs.append(player.queue.get_nowait())
            except Exception:
                break
        random.shuffle(songs)
        for song in songs:
            await player.queue.put(song)
        await ctx.send(embed=discord.Embed(description='Shuffled', color=0xFFC0CB))


async def setup(bot):
    await bot.add_cog(Music(bot))
