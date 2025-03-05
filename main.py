from __future__ import annotations
import json
import logging
import os
from pathlib import Path
import sys
import asyncio
import discord
import discord.gateway
import discord.opus
from discord import app_commands
from discord.ext import commands

from play import Wave, morse_msg
from room import Room
from view import RoomView

SRCDIR = Path(__file__).resolve().parent

with open(SRCDIR / 'config.json') as f:
    CONFIG = json.load(f)

# logging config
if len(sys.argv) <= 1 or sys.argv[1].startswith('-'):
    log_handler = logging.StreamHandler(sys.stdout)
else:
    log_handler = logging.FileHandler(sys.argv[1], 'a')
logging.basicConfig(format='{asctime} {levelname}\t {name:19} {message}',
                    style='{', handlers=[log_handler], level=logging.INFO)
logging.getLogger('discord').setLevel(logging.INFO)
logging.getLogger('discord.ext.commands').setLevel(logging.ERROR)
if '-v' in sys.argv:
    logging.getLogger('discord.app_commands').setLevel(logging.DEBUG)
logger = logging.getLogger('sfbm')
logger.setLevel(logging.DEBUG)

async def send_error(method, msg):
    embed = discord.Embed(
        title='Error',
        description=msg,
        color=0xff0000
    )
    try:
        await method(embed=embed, ephemeral=True)
    except TypeError:
        await method(embed=embed)

class MorseTree(app_commands.CommandTree):

    client: SFBM
    async def on_error(
        self, ctx: discord.Interaction, exc: app_commands.AppCommandError
    ) -> None:
        logger.error('Ignoring exception in command %r - %s: %s',
                    ctx.command.qualified_name if ctx.command else 'None',
                    type(exc).__name__, exc)
        if ctx.command and ctx.command.on_error:
            return # on_error called
        if isinstance(exc, (
            app_commands.BotMissingPermissions,
            app_commands.MissingPermissions,
            app_commands.CommandOnCooldown,
        )):
            if ctx.response.is_done():
                method = ctx.followup.send
            else:
                method = ctx.response.send_message

            await send_error(method, str(exc))
            return
        if isinstance(exc, (
            app_commands.CheckFailure,
            app_commands.CommandNotFound,
        )):
            return
        logger.error('', exc_info=exc)

    async def interaction_check(self, ctx: discord.Interaction) -> bool:
        if not isinstance(ctx.command, app_commands.Command):
            return False # we shouldn't have anything other than these
        logger.info('User %s\t(%18d) in channel %s\t(%18d) '
                    'running /%s',
                    ctx.user, ctx.user.id, ctx.channel,
                    ctx.channel.id if ctx.channel else '(none)',
                    ctx.command.qualified_name)
        return True

class SFBM(commands.Bot):

    def __init__(self) -> None:
        super().__init__(
            description='Communicate with Morse code',
            command_prefix='/',
            intents=discord.Intents.default(),
            help_command=None,
            activity=discord.Activity(type=discord.ActivityType.listening, name='/'),
            tree_cls=MorseTree,
        )

    async def setup_hook(self) -> None:
        asyncio.create_task(self.wakeup())

        guild_ids = CONFIG.get('guild_id')
        if isinstance(guild_ids, int):
            guild_ids = [guild_ids]
        if isinstance(guild_ids, list):
            for guild_id in guild_ids:
                guild = discord.Object(guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def wakeup(self):
        await client.wait_until_ready()
        mtimes = {path: os.path.getmtime(path) for path in Path(__file__).parent.glob('**.py')}
        while 1:
            for path, mtime in mtimes.items():
                if os.path.getmtime(path) > mtime:
                    await client.close()
            await asyncio.sleep(1)

client = SFBM()

rooms: dict[str, Room] = {}

@client.tree.command(description='Join a Morse room')
@app_commands.describe(
    name='The name of the room to join.',
    net='If this is a new room, you become the host; only one person you specify can speak at a time.',
)
async def join(ctx: discord.Interaction, name: str, net: bool = False) -> None:
    assert isinstance(ctx.channel, discord.TextChannel)
    assert isinstance(ctx.user, discord.Member)
    assert ctx.guild is not None
    # join user's voice channel
    if ctx.user.voice is None or ctx.user.voice.channel is None:
        await send_error(ctx.response.send_message, "You're not in a voice channel!")
        return
    if ctx.guild.voice_client is not None:
        await send_error(ctx.response.send_message, 'Already in a voice channel!')
        return
    try:
        vc = await ctx.user.voice.channel.connect()
    except discord.Forbidden:
        await send_error(ctx.response.send_message, "Couldn't join your voice channel.")
        return
    wave = Wave()
    try:
        vc.play(wave, application='audio', signal_type='music')
    except discord.Forbidden:
        await send_error(ctx.response.send_message, "Can't speak in your voice channel.")
        await vc.disconnect()
        return
    # get a handle on the message for later editing
    msg = await ctx.response.defer()
    assert msg and msg.message_id is not None
    msg = ctx.channel.get_partial_message(msg.message_id)
    # clean up empty rooms so that they can be reinitialized
    for key in [key for key, value in rooms.items() if not value.views]:
        del rooms[key]
    # get or create room
    if name not in rooms:
        room = Room(name, net=net)
        if room.net:
            room._host = room._speaking = (ctx.guild, ctx.user)
        rooms[name] = room
    else:
        room = rooms[name]
    # create local view of room
    view = RoomView(msg=msg, room=room, audio=wave, user=(ctx.guild, ctx.user))
    room.views.add(view)
    # display view
    await ctx.edit_original_response(embed=view.make_embed(), view=view)

@client.tree.command(description='Convert text to Morse')
@app_commands.describe(text='Text to translate to Morse')
async def morse(ctx: discord.Interaction, text: str) -> None:
    await ctx.response.send_message(f'```\n{morse_msg(text)}\n```', ephemeral=True)

try:
    client.run(CONFIG['token'], log_handler=None)
except KeyboardInterrupt:
    pass
