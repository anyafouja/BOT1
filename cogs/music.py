import asyncio
import discord
import random
import itertools
import os
import json
import re
import urllib.request
import urllib.parse
from discord.ext import commands
from yt_dlp import YoutubeDL
from yt_dlp.networking.impersonate import ImpersonateTarget

FFMPEG_OPTIONS = {
    'before_options': (
        '-reconnect 1 '
        '-reconnect_streamed 1 '
        '-reconnect_delay_max 5 '
        '-reconnect_on_network_error 1 '
    ),
    'options': '-vn',
}

INVIDIOUS_INSTANCES = [
    'inv.thepixora.com',
]


def _extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL."""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'^([0-9A-Za-z_-]{11})$',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _invidious_api(endpoint: str, instance_idx: int = 0) -> dict:
    """Query Invidious API with fallback to other instances."""
    for i in range(len(INVIDIOUS_INSTANCES)):
        idx = (instance_idx + i) % len(INVIDIOUS_INSTANCES)
        instance = INVIDIOUS_INSTANCES[idx]
        try:
            url = f'https://{instance}{endpoint}'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode())
        except Exception:
            continue
    raise RuntimeError('All Invidious instances failed')


def _invidious_search(query: str) -> dict:
    """Search YouTube via Invidious and return first result."""
    endpoint = f'/api/v1/search?q={urllib.parse.quote(query)}'
    results = _invidious_api(endpoint)
    if not results or not isinstance(results, list):
        raise RuntimeError('No search results')
    video = next((r for r in results if r.get('type') == 'video'), None)
    if not video:
        raise RuntimeError('No video found')
    return _invidious_get_video(video['videoId'])


def _invidious_get_video(video_id: str) -> dict:
    """Get video info from Invidious and convert to yt-dlp format."""
    endpoint = f'/api/v1/videos/{video_id}'
    data = _invidious_api(endpoint)
    
    # Find best audio format
    audio_formats = [f for f in data.get('adaptiveFormats', []) 
                     if f.get('type', '').startswith('audio/')]
    if not audio_formats:
        raise RuntimeError('No audio formats available')
    
    # Sort by bitrate, pick best
    best_audio = max(audio_formats, key=lambda f: f.get('bitrate', 0))
    
    # Convert to yt-dlp format
    return {
        'id': data.get('videoId'),
        'title': data.get('title'),
        'url': best_audio.get('url'),
        'webpage_url': f'https://www.youtube.com/watch?v={video_id}',
        'thumbnail': data.get('videoThumbnails', [{}])[0].get('url'),
        'duration': data.get('lengthSeconds'),
        'ext': 'webm' if 'webm' in best_audio.get('type', '') else 'm4a',
    }


def _extract_info(url: str) -> dict:
    # Try yt-dlp first
    is_search = not re.match(r'https?://', url)
    if is_search:
        url = 'ytsearch:' + url
    
    cookie_file = os.environ.get('YT_COOKIES_FILE') or 'cookies.txt'
    opts = {
        'format': 'bestaudio/best',
        'default_search': 'auto',
        'quiet': True,
        'no_warnings': True,
        'extractor_retries': 10,
        'socket_timeout': 30,
        'impersonate': ImpersonateTarget.from_str('chrome-116:windows-10'),
    }
    if os.path.isfile(cookie_file):
        opts['cookiefile'] = cookie_file
    
    try:
        ydl = YoutubeDL(opts)
        data = ydl.extract_info(url, download=False)
        if 'entries' in data:
            data = data['entries'][0]
        return data
    except Exception as e:
        error_msg = str(e)
        # If blocked by YouTube, fall back to Invidious
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            try:
                if is_search:
                    # Extract search query (remove 'ytsearch:' prefix)
                    query = url.replace('ytsearch:', '')
                    return _invidious_search(query)
                else:
                    # Extract video ID from URL
                    video_id = _extract_video_id(url)
                    if video_id:
                        return _invidious_get_video(video_id)
                    raise RuntimeError('Invalid YouTube URL')
            except Exception as inv_error:
                raise RuntimeError(f'yt-dlp failed: {error_msg}; Invidious failed: {inv_error}')
        raise RuntimeError(error_msg)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.thumbnail = data.get('thumbnail')
        self.webpage_url = data.get('webpage_url')

    @classmethod
    async def from_data(cls, data: dict, volume=0.5):
        stream_url = data['url']
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        return cls(source, data=data, volume=volume)

    @classmethod
    async def from_url(cls, url: str, volume=0.5):
        data = await asyncio.get_event_loop().run_in_executor(None, _extract_info, url)
        return await cls.from_data(data, volume=volume)


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
                    item = (self.current.title, self.current.webpage_url)
                else:
                    item = await asyncio.wait_for(self.queue.get(), timeout=300)
            except asyncio.TimeoutError:
                await self._cog.cleanup(self._guild)
                return
            except asyncio.CancelledError:
                return

            if isinstance(item, str):
                url = item
                title = url
                data = None
            else:
                title = item[0]
                url = item[1]
                data = item[2] if len(item) >= 3 else None

            try:
                if data:
                    source = await YTDLSource.from_data(data, volume=self.volume)
                else:
                    source = await YTDLSource.from_url(url, volume=self.volume)
            except Exception as e:
                await self._channel.send(f'Error processing song: `{e}`')
                continue

            self.current = source

            vc = self._guild.voice_client
            if not vc:
                await self._channel.send('Lost connection to voice channel.')
                await self._cog.cleanup(self._guild)
                return

            try:
                vc.play(source, after=self._after_playing)
            except Exception as e:
                await self._channel.send(f'Error starting playback: `{e}`')
                self.current = None
                continue

            view = NowPlayingView(self, self._guild.id)

            try:
                embed = discord.Embed(title=source.title, color=0xFFC0CB)
                if self.np:
                    try:
                        await self.np.delete()
                    except Exception:
                        pass
                self.np = await self._channel.send(embed=embed, view=view)
            except Exception:
                pass

            try:
                await asyncio.wait_for(self._finished.wait(), timeout=600)
            except asyncio.TimeoutError:
                vc = self._guild.voice_client
                if vc:
                    vc.stop()

            if not self._stop and self.current:
                self.history.append((self.current.title, self.current.webpage_url))
                if len(self.history) > 20:
                    self.history.pop(0)

            try:
                source.cleanup()
            except Exception:
                pass

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
            vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label='||', style=discord.ButtonStyle.secondary)
    async def pause_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message('Not connected.', ephemeral=True)
        if vc.is_paused():
            vc.resume()
            button.label = '||'
        elif vc.is_playing():
            vc.pause()
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
            vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label='\u27F3', style=discord.ButtonStyle.secondary)
    async def loop_(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        player.loop = not player.loop
        button.label = '\u27F2' if player.loop else '\u27F3'
        await interaction.response.edit_message(view=self)


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
                player._finished.set()
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
            await guild.voice_client.disconnect(force=True)
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

    @commands.hybrid_command(name='play', aliases=['p'])
    async def play_(self, ctx, *, search: str):
        """Plays a song from YouTube."""
        async with ctx.typing():
            vc = ctx.voice_client
            if not vc:
                if ctx.author.voice:
                    try:
                        await ctx.author.voice.channel.edit(rtc_region='singapore')
                    except Exception:
                        pass
                    vc = await ctx.author.voice.channel.connect(reconnect=True)
                else:
                    return await ctx.send('You are not connected to a voice channel.')
            elif ctx.author.voice and vc.channel != ctx.author.voice.channel:
                await vc.move_to(ctx.author.voice.channel)

            try:
                data = await asyncio.get_event_loop().run_in_executor(
                    None, _extract_info, search
                )
                title = data.get('title', search)
                url = data.get('webpage_url', search)
                queue_item = (title, url, data)
            except Exception as e:
                await ctx.send(f'Failed to search for song: `{e}`')
                return

        player = await self.get_player(ctx)
        await player.queue.put(queue_item)

        embed = discord.Embed(title='Added to Queue', color=0xFFC0CB)
        embed.description = f'[{title}]({url})'
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='skip', aliases=['s'])
    async def skip_(self, ctx):
        """Skips the current song."""
        vc = ctx.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await ctx.send('Nothing is playing.')
        player = await self.get_player(ctx)
        player._stop = True
        vc.stop()
        player.current = None
        await ctx.send(embed=discord.Embed(description='Skipped', color=0xFFC0CB))

    @commands.hybrid_command(name='stop')
    async def stop_(self, ctx):
        """Stops playback and disconnects the bot."""
        vc = ctx.voice_client
        if not vc or not vc.is_connected():
            return await ctx.send('Not connected.')
        await self.cleanup(ctx.guild)
        await ctx.send(embed=discord.Embed(description='Stopped', color=0xFFC0CB))

    @commands.hybrid_command(name='pause')
    async def pause_(self, ctx):
        """Pauses the music."""
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send(embed=discord.Embed(description='Paused', color=0xFFC0CB))
        else:
            await ctx.send('Nothing is playing.')

    @commands.hybrid_command(name='resume')
    async def resume_(self, ctx):
        """Resumes the paused music."""
        vc = ctx.voice_client
        if vc and vc.is_paused():
            vc.resume()
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
            f"**{i+1}.** {item[0]}" for i, item in enumerate(upcoming)
        )
        await ctx.send(embed=discord.Embed(title='Queue', description=fmt, color=0xFFC0CB))

    @commands.hybrid_command(name='volume', aliases=['vol'])
    async def change_volume(self, ctx, vol: int):
        """Changes the bot volume (1-100)."""
        vc = ctx.voice_client
        if not vc or not 0 < vol <= 100:
            return await ctx.send('Invalid volume (1-100).')
        player = await self.get_player(ctx)
        player.volume = vol / 100
        if vc.source:
            vc.source.volume = vol / 100
        await ctx.send(embed=discord.Embed(description=f'Volume: {vol}%', color=0xFFC0CB))

    @commands.hybrid_command(name='help')
    async def help_(self, ctx):
        """Shows all commands."""
        cmds = [
            ('play <query>', 'Plays a song from YouTube'),
            ('skip', 'Skips the current song'),
            ('stop', 'Stops playback and disconnects'),
            ('pause', 'Pauses playback'),
            ('resume', 'Resumes playback'),
            ('volume <1-100>', 'Sets the volume'),
            ('queue', 'Shows the song queue'),
            ('clear-queue', 'Clears all queued songs'),
            ('shuffle', 'Shuffles the queue'),
            ('loop', 'Toggles loop mode'),
            ('ping', 'Checks bot latency'),
        ]
        embed = discord.Embed(title='Cachy Music', color=0xFFC0CB)
        embed.description = '\n\n'.join(f'**cachy {cmd}**\n{desc}' for cmd, desc in cmds)
        embed.set_footer(text='Powered by YouTube')
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
