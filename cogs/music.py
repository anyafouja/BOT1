import asyncio
import discord
import json
import os
import re
import time
import aiohttp
from collections import deque
from discord.ext import commands


YT_OAUTH_REFRESH = os.getenv('YT_OAUTH_REFRESH', '')
INNERTUBE_KEY = 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8'
INNERTUBE_API = 'https://www.youtube.com/youtubei/v1/player?key=' + INNERTUBE_KEY
OAUTH_TOKEN_URL = 'https://www.youtube.com/o/oauth2/token'
CLIENT_ID = '861556708454-d6dlm3lh05idd8npek18k6be8ba3oc68.apps.googleusercontent.com'
CLIENT_SECRET = 'SboVhoG9s0rNafixCSGGKXAT'

_oauth_token: str | None = None
_oauth_expiry: float = 0


async def refresh_oauth_token() -> str | None:
    global _oauth_token, _oauth_expiry
    rt = YT_OAUTH_REFRESH
    if not rt:
        return None
    if _oauth_token and time.time() < _oauth_expiry:
        return _oauth_token
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OAUTH_TOKEN_URL, data={
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'refresh_token': rt,
                'grant_type': 'refresh_token',
            }) as resp:
                data = await resp.json()
                if 'access_token' not in data:
                    print(f'[OAUTH_ERROR] Refresh failed: {data}')
                    return None
                _oauth_token = data.get('access_token')
                _oauth_expiry = time.time() + data.get('expires_in', 3600) - 60
                return _oauth_token
    except Exception as e:
        print(f'[OAUTH_EXCEPTION] {e}')
        return None


async def search_youtube(query: str) -> list[dict]:
    async with aiohttp.ClientSession() as session:
        payload = {
            'context': {
                'client': {
                    'clientName': 'WEB',
                    'clientVersion': '2.20240101.00.00',
                }
            },
            'query': query,
        }
        async with session.post(
            'https://www.youtube.com/youtubei/v1/search?key=' + INNERTUBE_KEY,
            json=payload
        ) as resp:
            data = await resp.json()

    results = []
    contents = (
        data.get('contents', {})
        .get('twoColumnSearchResultsRenderer', {})
        .get('primaryContents', {})
        .get('sectionListRenderer', {})
        .get('contents', [])
    )
    for section in contents:
        items = section.get('itemSectionRenderer', {}).get('contents', [])
        for item in items:
            vr = item.get('videoRenderer', {})
            if not vr:
                continue
            vid = vr.get('videoId', '')
            if not vid:
                continue
            title_runs = vr.get('title', {}).get('runs', [])
            title = ''.join(r.get('text', '') for r in title_runs)
            thumb = ''
            thumbs = vr.get('thumbnail', {}).get('thumbnails', [])
            if thumbs:
                thumb = thumbs[-1].get('url', '')
            duration = 0
            dur_str = vr.get('lengthText', {}).get('simpleText', '')
            if dur_str:
                parts = list(map(int, re.findall(r'\d+', dur_str)))
                if len(parts) == 3:
                    duration = parts[0] * 3600 + parts[1] * 60 + parts[2]
                elif len(parts) == 2:
                    duration = parts[0] * 60 + parts[1]
                elif len(parts) == 1:
                    duration = parts[0]
            author = ''
            owner = vr.get('ownerText', {}).get('runs', [])
            if owner:
                author = owner[0].get('text', '')
            results.append({
                'id': vid,
                'title': title,
                'thumbnail': thumb,
                'duration': duration,
                'author': author,
                'webpage_url': f'https://youtube.com/watch?v={vid}',
            })
    return results


_last_youtube_error: str | None = None

async def get_audio_url(video_id: str) -> str | None:
    global _last_youtube_error
    token = await refresh_oauth_token()
    if not token:
        _last_youtube_error = 'OAuth token refresh returned no token'
        return None

    async with aiohttp.ClientSession() as session:
        payload = {
            'context': {
                'client': {
                    'clientName': 'TVHTML5',
                    'clientVersion': '7.20201028',
                }
            },
            'videoId': video_id,
        }
        headers = {'Authorization': f'Bearer {token}'}
        async with session.post(INNERTUBE_API, json=payload, headers=headers) as resp:
            data = await resp.json()

    api_err = data.get('error')
    if api_err:
        _last_youtube_error = f'InnerTube player error: {api_err}'
        return None

    sd = data.get('streamingData') or {}
    if not sd:
        keys = list(data.keys())[:10]
        _last_youtube_error = f'No streamingData in response. Keys: {keys}'
        if 'responseContext' in data:
            sv = data['responseContext'].get('serviceTrackingParams', [])
            if sv:
                _last_youtube_error += f' serviceTracking: {len(sv)} entries'
        return None

    fmts = sd.get('adaptiveFormats', []) + sd.get('formats', [])

    if not fmts:
        _last_youtube_error = 'No formats in streamingData'
        return None

    def sort_key(f):
        mt = f.get('mimeType', '')
        score = 0
        if 'opus' in mt: score = 3
        elif 'mp4a' in mt or 'm4a' in mt: score = 2
        elif 'audio' in mt: score = 1
        return score

    fmts.sort(key=sort_key, reverse=True)

    for f in fmts:
        url = f.get('url', '')
        if url and ('audio' in f.get('mimeType', '') or 'opus' in f.get('mimeType', '')):
            return url
    for f in fmts:
        url = f.get('url', '')
        if url:
            return url
    _last_youtube_error = f'No usable URL in {len(fmts)} formats'
    return None


class Track:
    def __init__(self, data: dict):
        self.id = data.get('id', '')
        self.title = data.get('title', 'Unknown')
        self.uri = data.get('webpage_url', f'https://youtube.com/watch?v={self.id}')
        self.artwork = data.get('thumbnail', '')
        self.duration = data.get('duration', 0)
        self.author = data.get('author', 'Unknown')
        self._url = None

    async def get_url(self) -> str | None:
        if self._url:
            return self._url
        self._url = await get_audio_url(self.id)
        return self._url


class MusicPlayer:
    def __init__(self, ctx: commands.Context):
        self.ctx = ctx
        self.bot = ctx.bot
        self.vc: discord.VoiceClient | None = None
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self._queue_list: list[Track] = []
        self.current: Track | None = None
        self.loop_mode = 0
        self.history: deque[Track] = deque(maxlen=20)
        self.np_message: discord.Message | None = None
        self.text_channel = ctx.channel
        self._paused = False
        self._stop = False

    @property
    def is_playing(self) -> bool:
        return self.vc and self.vc.is_playing()

    @property
    def is_paused(self) -> bool:
        return self.vc and self.vc.is_paused()

    async def connect(self, channel: discord.VoiceChannel) -> None:
        try:
            await channel.edit(rtc_region='singapore')
        except Exception:
            pass
        self.vc = await channel.connect()

    async def disconnect(self) -> None:
        self._stop = True
        if self.np_message:
            try:
                await self.np_message.delete()
            except Exception:
                pass
            self.np_message = None
        if self.vc:
            try:
                await self.vc.disconnect(force=True)
            except Exception:
                pass
            self.vc = None
        guild_id = self.ctx.guild.id
        self.bot.voice_players.pop(guild_id, None)

    async def _play(self, track: Track) -> None:
        self.current = track
        url = await track.get_url()
        if not url:
            err_msg = _last_youtube_error or 'Unknown error'
            await self.text_channel.send(f'Failed to get audio URL: {err_msg}')
            return await self._next()

        ffmpeg_opts = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 0',
            'options': '-vn -bufsize 64k',
        }
        source = discord.FFmpegPCMAudio(url, **ffmpeg_opts)
        self.vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._on_end(), self.bot.loop))
        self._paused = False
        await self._show_np(track)

    async def _on_end(self) -> None:
        if self._stop:
            return
        self.history.append(self.current)
        if self.loop_mode == 1:
            await self._play(self.current)
        else:
            await self._next()

    async def _next(self) -> None:
        try:
            track = await asyncio.wait_for(self.queue.get(), timeout=300)
            if self.loop_mode == 2:
                self.queue.put_nowait(self.current)
            self._queue_list.pop(0)
            await self._play(track)
        except asyncio.TimeoutError:
            await self.text_channel.send('Queue empty, disconnecting.')
            await self.disconnect()

    async def start(self) -> None:
        self._stop = False
        if self.current:
            return
        try:
            track = await asyncio.wait_for(self.queue.get(), timeout=300)
            await self._play(track)
        except asyncio.TimeoutError:
            await self.disconnect()

    async def enqueue(self, track: Track) -> None:
        await self.queue.put(track)
        self._queue_list.append(track)

    async def skip(self) -> None:
        if self.vc and self.vc.is_playing():
            self.vc.stop()

    async def pause(self) -> None:
        if self.vc and self.vc.is_playing():
            self.vc.pause()
            self._paused = True

    async def resume(self) -> None:
        if self.vc and self.vc.is_resumable():
            self.vc.resume()
            self._paused = False

    def get_queue(self) -> list[Track]:
        return list(self._queue_list)

    def clear_queue(self) -> None:
        self._queue_list.clear()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def shuffle_queue(self) -> None:
        import random
        random.shuffle(self._queue_list)
        new_q = asyncio.Queue()
        for t in self._queue_list:
            new_q.put_nowait(t)
        self.queue = new_q

    async def _show_np(self, track: Track) -> None:
        view = NowPlayingView(self, self.ctx.guild.id)
        embed = discord.Embed(color=0xFFC0CB)
        if track.artwork:
            embed.set_image(url=track.artwork)
        if self.np_message:
            try:
                await self.np_message.delete()
            except Exception:
                pass
        try:
            self.np_message = await self.text_channel.send(embed=embed, view=view)
        except Exception:
            pass


class NowPlayingView(discord.ui.View):
    def __init__(self, player: MusicPlayer, guild_id: int):
        super().__init__(timeout=None)
        self.player = player
        self.guild_id = guild_id
        self._pause_button.label = '||'

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
        if not player.history:
            return await interaction.response.send_message('No previous song.', ephemeral=True)
        prev = player.history.pop()
        await player.enqueue(prev)
        if player.is_playing or player.is_paused:
            await player.skip()
        else:
            await player.start()
        await interaction.response.defer()

    @discord.ui.button(label='||', style=discord.ButtonStyle.secondary)
    async def pause_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        if player.is_paused:
            await player.resume()
            button.label = '||'
        elif player.is_playing:
            await player.pause()
            button.label = '\u25B7'
        else:
            return await interaction.response.send_message('Nothing playing.', ephemeral=True)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label='\u25B7\u25B7', style=discord.ButtonStyle.secondary)
    async def next_(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        if not player.is_playing and not player.is_paused:
            return await interaction.response.send_message('Nothing playing.', ephemeral=True)
        await player.skip()
        await interaction.response.defer()

    @discord.ui.button(label='\u27F3', style=discord.ButtonStyle.secondary)
    async def loop_(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        if player.loop_mode == 0:
            player.loop_mode = 1
            button.label = '\u27F2'
        elif player.loop_mode == 1:
            player.loop_mode = 2
            button.label = '\u27F2'
        else:
            player.loop_mode = 0
            button.label = '\u27F3'
        await interaction.response.edit_message(view=self)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.voice_players = {}

    async def get_player(self, ctx) -> MusicPlayer:
        guild_id = ctx.guild.id
        if guild_id not in self.bot.voice_players:
            player = MusicPlayer(ctx)
            if ctx.author.voice:
                await player.connect(ctx.author.voice.channel)
            else:
                raise RuntimeError('Not connected to a voice channel.')
            self.bot.voice_players[guild_id] = player
        else:
            player = self.bot.voice_players[guild_id]
            if ctx.author.voice and player.vc and player.vc.channel != ctx.author.voice.channel:
                await player.vc.move_to(ctx.author.voice.channel)
        player.text_channel = ctx.channel
        return player

    async def cleanup(self, guild) -> None:
        player = self.bot.voice_players.pop(guild.id, None)
        if player:
            await player.disconnect()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id == self.bot.user.id:
            if after.channel is None:
                await self.cleanup(member.guild)
            return
        vc = member.guild.voice_client
        if vc and vc.channel:
            real = [m for m in vc.channel.members if not m.bot]
            if len(real) == 0:
                await asyncio.sleep(60)
                vc = member.guild.voice_client
                if vc and vc.channel:
                    real = [m for m in vc.channel.members if not m.bot]
                    if len(real) == 0:
                        await self.cleanup(member.guild)

    @commands.hybrid_command(name='play', aliases=['p'])
    async def play_(self, ctx, *, search: str):
        """Play a song from YouTube."""
        await ctx.defer()
        try:
            player = await self.get_player(ctx)
        except RuntimeError as e:
            await ctx.send(str(e))
            return
        except Exception as e:
            await ctx.send(str(e))
            return

        try:
            results = await search_youtube(search)
        except Exception as e:
            await ctx.send(f'Search failed: {e}')
            return

        if not results:
            await ctx.send('No results found.')
            return

        tracks = [Track(r) for r in results]
        track = tracks[0]
        await player.enqueue(track)
        embed = discord.Embed(description=f'[{track.title}]({track.uri})', color=0xFFC0CB)
        await ctx.send(embed=embed)

        if not player.is_playing and not player.is_paused:
            await player.start()

    @commands.hybrid_command(name='skip', aliases=['s'])
    async def skip_(self, ctx):
        """Skip the current song."""
        player = self.bot.voice_players.get(ctx.guild.id)
        if not player or not player.is_playing:
            return await ctx.send('Nothing playing.')
        await player.skip()
        await ctx.send(embed=discord.Embed(description='Skipped', color=0xFFC0CB))

    @commands.hybrid_command(name='stop')
    async def stop_(self, ctx):
        """Stop playback and disconnect."""
        vc = ctx.voice_client
        if not vc or not vc.is_connected():
            return await ctx.send('Not connected.')
        await self.cleanup(ctx.guild)
        await ctx.send(embed=discord.Embed(description='Disconnected', color=0xFFC0CB))

    @commands.hybrid_command(name='pause')
    async def pause_(self, ctx):
        """Pause the music."""
        player = self.bot.voice_players.get(ctx.guild.id)
        if player and player.is_playing:
            await player.pause()
            await ctx.send(embed=discord.Embed(description='Paused', color=0xFFC0CB))
        else:
            await ctx.send('Nothing playing.')

    @commands.hybrid_command(name='resume')
    async def resume_(self, ctx):
        """Resume the music."""
        player = self.bot.voice_players.get(ctx.guild.id)
        if player and player.is_paused:
            await player.resume()
            await ctx.send(embed=discord.Embed(description='Resumed', color=0xFFC0CB))
        else:
            await ctx.send('Not paused.')

    @commands.hybrid_command(name='queue', aliases=['q'])
    async def queue_info(self, ctx):
        """Show the song queue."""
        player = self.bot.voice_players.get(ctx.guild.id)
        if not player:
            return await ctx.send('Queue is empty.')
        upcoming = player.get_queue()
        if not upcoming:
            return await ctx.send('Queue is empty.')
        track_count = len(upcoming)
        max_tracks = 10
        lines = []
        for i, t in enumerate(upcoming[:max_tracks], 1):
            lines.append(f'**{i}.** {t.title}')
        if track_count > max_tracks:
            lines.append(f'*... and {track_count - max_tracks} more*')
        embed = discord.Embed(title=f'Queue ({track_count})', description='\n'.join(lines), color=0xFFC0CB)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='volume', aliases=['vol'])
    async def change_volume(self, ctx, vol: int):
        """Set volume (1-100)."""
        if not 0 < vol <= 100:
            return await ctx.send('Invalid volume (1-100).')
        player = self.bot.voice_players.get(ctx.guild.id)
        if player and player.vc:
            player.vc.source.volume = vol / 100
            await ctx.send(embed=discord.Embed(description=f'Volume: {vol}%', color=0xFFC0CB))
        else:
            await ctx.send('Not connected.')

    @commands.hybrid_command(name='ping')
    async def ping_(self, ctx):
        """Check bot latency."""
        await ctx.send(embed=discord.Embed(description=f'Pong! {round(self.bot.latency * 1000)}ms', color=0xFFC0CB))

    @commands.hybrid_command(name='clear-queue')
    async def clear_queue_(self, ctx):
        """Clear all songs from the queue."""
        player = self.bot.voice_players.get(ctx.guild.id)
        if not player:
            return await ctx.send('No queue to clear.')
        player.clear_queue()
        await ctx.send(embed=discord.Embed(description='Queue cleared', color=0xFFC0CB))

    @commands.hybrid_command(name='loop')
    async def loop_(self, ctx):
        """Toggle looping (off -> single -> queue)."""
        player = self.bot.voice_players.get(ctx.guild.id)
        if not player:
            return await ctx.send('Not connected.')
        if player.loop_mode == 0:
            player.loop_mode = 1
            text = 'Loop: single'
        elif player.loop_mode == 1:
            player.loop_mode = 2
            text = 'Loop: queue'
        else:
            player.loop_mode = 0
            text = 'Loop: off'
        await ctx.send(embed=discord.Embed(description=text, color=0xFFC0CB))

    @commands.hybrid_command(name='shuffle')
    async def shuffle_(self, ctx):
        """Shuffle the queue."""
        player = self.bot.voice_players.get(ctx.guild.id)
        if not player or not player.get_queue():
            return await ctx.send('Queue is empty.')
        player.shuffle_queue()
        await ctx.send(embed=discord.Embed(description='Shuffled', color=0xFFC0CB))

    @commands.hybrid_command(name='nowplaying', aliases=['np'])
    async def nowplaying_(self, ctx):
        """Show currently playing song."""
        player = self.bot.voice_players.get(ctx.guild.id)
        if not player or not player.current:
            return await ctx.send('Nothing playing.')
        track = player.current
        embed = discord.Embed(color=0xFFC0CB)
        if track.artwork:
            embed.set_image(url=track.artwork)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Music(bot))
