import asyncio
import discord
from collections import deque
from discord.ext import commands
import wavelink
from wavelink import QueueMode


class CachyPlayer(wavelink.Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text_channel: discord.TextChannel | None = None
        self.np_message: discord.Message | None = None
        self.loop_mode: int = 0
        self._last_tracks: deque[wavelink.Playable] = deque(maxlen=20)

    async def destroy(self):
        if self.np_message:
            try:
                await self.np_message.delete()
            except Exception:
                pass
            self.np_message = None
        try:
            await self.disconnect(force=True)
        except Exception:
            pass
        await super().destroy()


class NowPlayingView(discord.ui.View):
    def __init__(self, player: CachyPlayer, guild_id: int):
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
        if not player._last_tracks:
            return await interaction.response.send_message('No previous song.', ephemeral=True)
        prev = player._last_tracks.pop()
        player.queue.put_at(0, prev)
        if player.playing or player.paused:
            await player.skip()
        else:
            await player.play(player.queue.get())
        await interaction.response.defer()

    @discord.ui.button(label='||', style=discord.ButtonStyle.secondary)
    async def pause_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        if player.paused:
            await player.pause(False)
            button.label = '||'
        elif player.playing:
            await player.pause(True)
            button.label = '\u25B7'
        else:
            return await interaction.response.send_message('Nothing playing.', ephemeral=True)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label='\u25B7\u25B7', style=discord.ButtonStyle.secondary)
    async def next_(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        if not player.playing and not player.paused:
            return await interaction.response.send_message('Nothing playing.', ephemeral=True)
        await player.skip()
        await interaction.response.defer()

    @discord.ui.button(label='\u27F3', style=discord.ButtonStyle.secondary)
    async def loop_(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        if player.loop_mode == 0:
            player.loop_mode = 1
            player.queue.mode = QueueMode.loop
            button.label = '\u27F2'
        elif player.loop_mode == 1:
            player.loop_mode = 2
            player.queue.mode = QueueMode.loop_all
            button.label = '\u27F2'
        else:
            player.loop_mode = 0
            player.queue.mode = QueueMode.normal
            button.label = '\u27F3'
        await interaction.response.edit_message(view=self)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.locks = {}

    async def cleanup(self, guild) -> None:
        player = guild.voice_client
        if player and isinstance(player, CachyPlayer):
            if player.np_message:
                try:
                    await player.np_message.delete()
                except Exception:
                    pass
                player.np_message = None
            try:
                await player.destroy()
            except Exception:
                pass
        self.locks.pop(guild.id, None)

    async def get_player(self, ctx) -> CachyPlayer:
        guild_id = ctx.guild.id
        if guild_id not in self.locks:
            self.locks[guild_id] = asyncio.Lock()
        async with self.locks[guild_id]:
            player = ctx.voice_client
            if not player or not isinstance(player, CachyPlayer):
                if ctx.author.voice:
                    try:
                        await ctx.author.voice.channel.edit(rtc_region='singapore')
                    except Exception:
                        pass
                    player = await ctx.author.voice.channel.connect(cls=CachyPlayer)
                    player.inactive_timeout = 60
                    player.text_channel = ctx.channel
                else:
                    raise RuntimeError('Not connected to a voice channel.')
            elif ctx.author.voice and player.channel != ctx.author.voice.channel:
                await player.move_to(ctx.author.voice.channel)
            player.text_channel = ctx.channel
            return player

    def get_cachy_player(self, guild) -> CachyPlayer | None:
        vc = guild.voice_client
        if vc and isinstance(vc, CachyPlayer):
            return vc
        return None

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player: CachyPlayer | None = payload.player
        if not player:
            return
        track = payload.original or payload.track
        if not player.text_channel:
            return

        view = NowPlayingView(player, player.guild.id)
        embed = discord.Embed(color=0xFFC0CB)
        if track.artwork:
            embed.set_image(url=track.artwork)

        if player.np_message:
            try:
                await player.np_message.delete()
            except Exception:
                pass
        try:
            player.np_message = await player.text_channel.send(embed=embed, view=view)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player: CachyPlayer | None = payload.player
        if not player or not payload.original:
            return
        if player.loop_mode == 0:
            player._last_tracks.append(payload.original)

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: CachyPlayer):
        await self.cleanup(player.guild)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id == self.bot.user.id:
            if after.channel is None:
                player = self.get_cachy_player(member.guild)
                if player:
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

        tracks = await wavelink.Playable.search(search, source=wavelink.TrackSource.YouTube)
        if not tracks:
            await ctx.send('No results found.')
            return
        if isinstance(tracks, wavelink.Playlist):
            for t in tracks:
                player.queue.put(t)
            embed = discord.Embed(description=f'Added {len(tracks)} songs from **{tracks.name}**', color=0xFFC0CB)
            await ctx.send(embed=embed)
        else:
            track = tracks[0]
            player.queue.put(track)
            embed = discord.Embed(description=f'[{track.title}]({track.uri})', color=0xFFC0CB)
            await ctx.send(embed=embed)

        if not player.playing:
            await player.play(player.queue.get())

    @commands.hybrid_command(name='skip', aliases=['s'])
    async def skip_(self, ctx):
        """Skip the current song."""
        player = self.get_cachy_player(ctx.guild)
        if not player or not player.playing:
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
        player = self.get_cachy_player(ctx.guild)
        if player and player.playing:
            await player.pause(True)
            await ctx.send(embed=discord.Embed(description='Paused', color=0xFFC0CB))
        else:
            await ctx.send('Nothing playing.')

    @commands.hybrid_command(name='resume')
    async def resume_(self, ctx):
        """Resume the music."""
        player = self.get_cachy_player(ctx.guild)
        if player and player.paused:
            await player.pause(False)
            await ctx.send(embed=discord.Embed(description='Resumed', color=0xFFC0CB))
        else:
            await ctx.send('Not paused.')

    @commands.hybrid_command(name='queue', aliases=['q'])
    async def queue_info(self, ctx):
        """Show the song queue."""
        player = self.get_cachy_player(ctx.guild)
        if not player or player.queue.is_empty:
            return await ctx.send('Queue is empty.')

        upcoming = list(player.queue.copy())
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
        player = self.get_cachy_player(ctx.guild)
        if not player or not 0 < vol <= 100:
            return await ctx.send('Invalid volume (1-100).')
        await player.set_volume(vol * 10)
        await ctx.send(embed=discord.Embed(description=f'Volume: {vol}%', color=0xFFC0CB))

    @commands.hybrid_command(name='ping')
    async def ping_(self, ctx):
        """Check bot latency."""
        await ctx.send(embed=discord.Embed(description=f'Pong! {round(self.bot.latency * 1000)}ms', color=0xFFC0CB))

    @commands.hybrid_command(name='clear-queue')
    async def clear_queue_(self, ctx):
        """Clear all songs from the queue."""
        player = self.get_cachy_player(ctx.guild)
        if not player:
            return await ctx.send('No queue to clear.')
        player.queue.clear()
        await ctx.send(embed=discord.Embed(description='Queue cleared', color=0xFFC0CB))

    @commands.hybrid_command(name='loop')
    async def loop_(self, ctx):
        """Toggle looping (off -> single -> queue)."""
        player = self.get_cachy_player(ctx.guild)
        if not player:
            return await ctx.send('Not connected.')
        if player.loop_mode == 0:
            player.loop_mode = 1
            player.queue.mode = QueueMode.loop
            text = 'Loop: single'
        elif player.loop_mode == 1:
            player.loop_mode = 2
            player.queue.mode = QueueMode.loop_all
            text = 'Loop: queue'
        else:
            player.loop_mode = 0
            player.queue.mode = QueueMode.normal
            text = 'Loop: off'
        await ctx.send(embed=discord.Embed(description=text, color=0xFFC0CB))

    @commands.hybrid_command(name='shuffle')
    async def shuffle_(self, ctx):
        """Shuffle the queue."""
        player = self.get_cachy_player(ctx.guild)
        if not player or player.queue.is_empty:
            return await ctx.send('Queue is empty.')
        player.queue.shuffle()
        await ctx.send(embed=discord.Embed(description='Shuffled', color=0xFFC0CB))

    @commands.hybrid_command(name='nowplaying', aliases=['np'])
    async def nowplaying_(self, ctx):
        """Show currently playing song."""
        player = self.get_cachy_player(ctx.guild)
        if not player or not player.current:
            return await ctx.send('Nothing playing.')
        track = player.current
        embed = discord.Embed(color=0xFFC0CB)
        if track.artwork:
            embed.set_image(url=track.artwork)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Music(bot))
