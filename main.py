import os
import time
import random
import traceback
import asyncio
from typing import Any
import discord
import discord.gateway
import discord.opus
from discord.ext import commands, tasks

#monkeypatch voice speaking op
async def _msg_hook(self: discord.gateway.DiscordVoiceWebSocket, *args: dict[str, Any]) -> None:
    msg = args[1]
    op = msg['op']
    data = msg['d']  # According to Discord this key is always given

    if op == self.SPEAKING:
        print(msg)
        user_id = int(data['user_id'])
        vc = self._connection

        if vc.guild:
            user = vc.guild.get_member(user_id)
        else:
            user = client.get_user(user_id)

        client.dispatch('speaking_update', user, data['speaking'])

discord.gateway.DiscordVoiceWebSocket._hook = _msg_hook

class SFBM(commands.Bot):

    async def setup_hook(self) -> None:
        await self.add_cog(Morse())
        set_playing_status.start()
        asyncio.create_task(self.wakeup())

    async def wakeup(self):
        await client.wait_until_ready()
        mtime = os.path.getmtime(__file__)
        while 1:
            if os.path.getmtime(__file__) > mtime:
                await client.close()
            await asyncio.sleep(1)

intents = discord.Intents.default()
intents.message_content = True
client = SFBM('=', description='Communicate with Morse code', intents=intents)

def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ')

@client.before_invoke
async def before_invoke(ctx):
    print(now(), ctx.author, 'ran', ctx.message.content)

@client.event
async def on_command_error(ctx, exc):
    if hasattr(ctx.command, 'on_error'):
        return
    cog = ctx.cog
    if cog:
        attr = 'cog_error'.format(cog)
        if hasattr(cog, attr):
            return
    if isinstance(exc, (
        commands.BotMissingPermissions,
        commands.MissingPermissions,
        commands.MissingRequiredArgument,
        commands.BadArgument,
        commands.CommandOnCooldown,
    )):
        return await ctx.send(embed=discord.Embed(
            title='Error',
            description=str(exc),
            color=0xff0000
        ))
    if isinstance(exc, (
        commands.CheckFailure,
        commands.CommandNotFound,
        commands.TooManyArguments,
    )):
        return
    print('Ignoring exception in command {}:\n{}'.format(
        ctx.command,
        ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    ), end='')

FREQ = 48000

class Wave(discord.AudioSource):

    def __init__(self, freq=440):
        self.freq = freq
        self.freqs = set()
        self.wav = self.wave()

    def wave(self):
        i = 0
        while 1:
            freqs = set(self.freqs)
            yield (
                sum(
                    i % int(FREQ / f) / FREQ
                    for f in freqs
                )
                / (len(freqs) or 1)
            )
            i += 1

    def read(self):
        return b''.join(
            int(i * 32767 + 32768).to_bytes(2, 'big') * 2
            for i, j in zip(self.wav, range(int(0.02 * FREQ)))
        )

rooms = {}

MORSE = {
    ' ': '/',
    'a': '.-',
    'b': '-...',
    'c': '-.-.',
    'd': '-..',
    'e': '.',
    'f': '..-.',
    'g': '--.',
    'h': '....',
    'i': '..',
    'j': '.---',
    'k': '-.-',
    'l': '.-..',
    'm': '--',
    'n': '-.',
    'o': '---',
    'p': '.--.',
    'q': '--.-',
    'r': '.-.',
    's': '...',
    't': '-',
    'u': '..-',
    'v': '...-',
    'w': '.--',
    'x': '-..-',
    'y': '-.--',
    'z': '--..',
    '0': '-----',
    '1': '.----',
    '2': '..---',
    '3': '...--',
    '4': '....-',
    '5': '.....',
    '6': '-....',
    '7': '--...',
    '8': '---..',
    '9': '----.',
    '.': '.-.-.-',
    ',': '--..--',
    ':': '---...',
    '?': '..--..',
    "'": '.----.',
    '-': '-....-',
    '/': '-..-.',
    '"': '.-..-.',
    '@': '.--.-.',
    '=': '-...-',
    '!': '---.'
}

def morse_msg(msg):
    return ' '.join(MORSE.get(i, '..--..') for i in msg.lower())

async def play_morse(msg, sources, wpm, freq):
    ditlength = 6 / (5 * max(15, wpm))
    pauselength = 6 / (5 * wpm)
    msg = '/'.join(
        ' '.join(
            '_'.join(
                i for i in j.strip()
                if i in '.-'
            )
            for j in k.strip().split()
        )
        for k in msg.split('/')
    )
    for i in msg:
        if i == '.':
            for r in sources:
                r.freqs.add(freq)
            await asyncio.sleep(ditlength)
        if i == '-':
            for r in sources:
                r.freqs.add(freq)
            await asyncio.sleep(ditlength * 3)
        if i == '_':
            for r in sources:
                r.freqs.discard(freq)
            await asyncio.sleep(ditlength)
        if i == ' ':
            for r in sources:
                r.freqs.discard(freq)
            await asyncio.sleep(pauselength * 3)
        if i == '/':
            for r in sources:
                r.freqs.discard(freq)
            await asyncio.sleep(pauselength * 7)
    for r in sources:
        r.freqs.discard(freq)

class Room:
    """Represents a Morse room."""
    def __init__(self, name, keyed=False, net=False, password=None):
        self.name = name
        self.keyed = keyed
        self.net = net
        self.password = password
        self.wavs = {}
        self.futs = {}
        if not self.keyed:
            self.wpms = {}
        self.speaking = None
        self.new_users = set()
        self.host = None
        self.messages = asyncio.Queue()
        self.task = asyncio.create_task(self.handle_msgs())

    @staticmethod
    def call(ctx):
        guild = str(ctx.guild.id)
        user = str(ctx.author.id)
        return (
            chr(65 + int(guild[-2:]) % 26)
            + chr(65 + int(guild[-4:-2]) % 26)
            + guild[1]
            + chr(65 + int(user[-2:]) % 26)
            + chr(65 + int(user[-4:-2]) % 26)
            + chr(65 + int(user[-6:-4]) % 26)
        )

    async def handle_msgs(self):
        """Background task that handles all messages."""
        if self.keyed:
            @client.listen()
            async def on_speaking_update(user, state):
                try:
                    for c in self.wavs:
                        if c.author == user:
                            ctx = c
                            break
                    else:
                        return
                    if self.net and self.speaking != ctx:
                        return
                    for c in self.wavs:
                        r = self.wavs[c]
                        if state & 1:
                            r.freqs.add(self.wavs[ctx].freq)
                        else:
                            r.freqs.discard(self.wavs[ctx].freq)
                except:
                    traceback.print_exc()
        try:
            while 1:
                ctx, msg = await self.messages.get()
                if self.net and await self.process_commands(msg, ctx):
                    continue
                if msg.content.startswith('users'):
                    if msg.author.id != ctx.author.id:
                        continue
                    print(now(), ctx.author, 'ran', msg.content)
                    await ctx.send('\n'.join(
                        self.call(i)
                        for i in self.wavs
                    ))
                    continue
                if self.net and msg.content == 'done':
                    if msg.author.id != ctx.author.id:
                        continue
                    if self.speaking == self.host:
                        continue
                    if self.speaking != ctx:
                        continue
                    print(now(), ctx.author, 'ran', msg.content)
                    await self.set_speaker(ctx)
                    continue
                if not self.keyed and msg.content.startswith('wpm'):
                    if msg.author.id != ctx.author.id:
                        continue
                    print(now(), ctx.author, 'ran', msg.content)
                    try:
                        self.wpms[ctx] = int(msg.content.split()[-1])
                    except ValueError:
                        continue
                    await ctx.send('WPM set to %s' % self.wpms[ctx])
                    continue
                if msg.content == 'bye':
                    if msg.author.id != ctx.author.id:
                        continue
                    print(now(), ctx.author, 'ran', msg.content)
                    self.futs[ctx].set_result(None)
                if self.keyed:
                    continue
                if not msg.content.startswith(('.', '-')):
                    continue
                if self.net and not msg.author.id in {ctx.author.id, client.user.id}:
                    continue
                if self.net and msg.author.id == client.user.id:
                    if not msg.content.endswith(ctx.author.mention):
                        continue
                await self.speak(msg.content, self.wavs[ctx], self.wpms[ctx])
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            return
        except:
            traceback.print_exc()
        finally:
            if self.keyed:
                client.remove_listener('speaking_update', on_speaking_update)

    async def connect(self, ctx, wav, fut):
        """Connects the wave to the room. Returns whether you are the host."""
        self.wavs[ctx] = wav
        self.futs[ctx] = fut
        if not self.keyed:
            self.wpms[ctx] = 15
        morsing = asyncio.create_task(play_morse(
            morse_msg(self.name), [wav], 30, 440
        ))
        if self.net:
            await ctx.send(f"""Joined your voice channel.
You are connected to **net** `{self.name}`.
Wait until you are allowed to speak.""" + (
                '\nOnce you may, use PTT to key Morse code.'
                if self.keyed
                else """
Once you may, send `-- --- .-. ... . / -.-. --- -.. .`
to play it to all connected users."""
            ))
            if len(self.wavs) == 1:
                await self.set_host(ctx)
                await self.set_speaking(ctx)
                await morsing
                return True
            self.new_users.add(ctx)
            await ctx.send(f'The net host is {self.host.author!s} \
({self.call(self.host)}). Feel free to DM them with any concerns.')
        else:
            await ctx.send(f"""Joined your voice channel.
You are connected to room `{self.name}`.""" + (
                '\nUse PTT to key Morse code.'
                if self.keyed
                else """
Send `-- --- .-. ... . / -.-. --- -.. .`
to play it to all connected users in the room."""
            ))
        await asyncio.gather(*(
            i.send(f'{self.call(ctx)} just joined the room!')
            for i in self.wavs
            if i != ctx
        ))
        await morsing
        return False

    async def disconnect(self, ctx):
        """Disconnects the wave from the room. Returns whether to destroy."""
        del self.wavs[ctx]
        del self.futs[ctx]
        if not self.keyed:
            del self.wpms[ctx]
        self.new_users.discard(ctx)
        if self.net:
            if self.host == ctx and len(self.wavs) > 0:
                nctx, nwav = self.wavs.popitem()
                self.wavs[nctx] = nwav
                await self.set_host(nctx)
            if self.speaking == ctx and len(self.wavs) > 0:
                await self.set_speaking(self.host)
        if len(self.wavs) <= 0:
            self.task.cancel()
            return True
        return False

    async def speak(self, content, wav, wpm, freq=None):
        """Speaks content in Morse. If not allowed to speak, fails silently."""
        if self.net and self.wavs.get(self.speaking, None) != wav:
            return
        await play_morse(
            content,
            list(self.wavs.values()),
            wpm,
            freq or wav.freq
        )

    async def set_speaking(self, ctx):
        """Host-only: sets the user who may speak."""
        if self.speaking is not None:
            await self.speaking.send('The net host has decided that you may no \
longer speak.')
        self.speaking = ctx
        await ctx.send('The net host has decided that you may now speak.')

    async def set_speaker(self, ctx):
        """Sets the host as speaker."""
        self.speaking = self.host
        await ctx.send('You are no longer speaking.')
        await self.host.send(f'{self.call(ctx)} is done speaking.')

    async def set_host(self, ctx):
        """Host-only: sets the new host."""
        old_host = None
        if self.host is not None:
            old_host = self.host
            await self.host.send('You are no longer the host.')
        self.host = ctx
        await self.host.send('You are now the host of this net!')
        await asyncio.gather(*(i.send(f'{self.host!s} ({self.call(self.host)}) \
is now the host of this net.') for i in self.wavs
if i != self.host and i != old_host))

    async def process_commands(self, msg, ctx):
        """Process net commands. Returns whether to skip sending Morse."""
        if not self.net:
            return False
        if ctx != self.host or msg.author.id != self.host.author.id:
            return False
        content = msg.content
        if content.startswith('host'):
            print(now(), ctx.author, 'ran', msg.content)
            call = content.split()[-1]
            for c in self.wavs:
                if self.call(c) == call:
                    await self.set_host(c)
                    return True
            await ctx.send('No user with that callsign')
            return True
        if content.startswith('speaker'):
            print(now(), ctx.author, 'ran', msg.content)
            call = content.split()[-1]
            for c in self.wavs:
                if self.call(c) == call:
                    await self.set_speaking(c)
                    await ctx.send('Speaking privileges transferred to %s'
                                   % self.call(c))
                    return True
            await ctx.send('No user with that callsign')
            return True
        return False

class Morse(commands.Cog):

    def cog_check(self, ctx):
        if ctx.guild is None:
            return False
        perms = ctx.channel.permissions_for(ctx.guild.me)
        return (
            perms.read_messages
            and perms.send_messages
            and perms.embed_links
            and perms.read_message_history
        )

    @commands.command()
    async def join(
        self, ctx, room, keyed: bool = False,
        net: bool = False, password: bool = False
    ):
        """Join or create a room and send Morse. PLEASE RUN `=help join`

        If the room does not exist, it will be created. If it does, you will
        join it; all arguments past `room` will be ignored. If `keyed` is false,
        send a message consisting solely of Morse code (or at least starting
        with a . or -) to interpret the message as Morse and send it at your
        WPM. You can also use the =morse command to translate text to Morse if
        needed. If `keyed` is true, use PTT to key Morse code to everyone in the
        room or net. Because the bot can only connect to one voice channel per
        server, anyone can join the voice channel with the bot and listen in;
        unless the room is a net, anyone may also send text-based Morse code for
        it to be transmitted. However, only the person who joined the bot to the
        voice channel may key Morse via PTT or use "transient commands":

        done: in a net, transfers speaking privileges back to the host
        wpm <N>: in a non-keyed room, sets your sending WPM to N.
            You start off at 15 WPM no matter what - change it after joining
            if necessary.
        bye: disconnects the bot
        users: returns a list of callsigns connected to the room

        Nets are a more formal type of room where one person (the host) decides
        who is allowed to speak at any given moment. This is useful for large
        rooms where it would be too chaotic if everyone were to speak at once.
        Only the host of a net may use the following transient commands:

        host <callsign>: transfers hosting privileges to the specified user
        speaker <callsign>: transfers speaking privileges to the specified user

        If `net` is true and the room did not previously exist, the room will be
        created as a net, with you as the host. If `password` is true, you will
        be asked to set the password for the net (and confirm it by sending it
        again), and all people wanting to join the net will asked for the
        correct password. The host's name and discriminator are revealed to all
        users of the net AND all users who look up the net via `=info`, so if
        you don't want to reveal this information, do not host a net.

        If the host decides to transfer their privileges to you, your name and
        discriminator will also be revealed to all users of the net, present and
        future. Otherwise you will only be identified by a callsign (which is
        calculated off of the server ID and your user ID, but irreversibly).
        If you don't want to have any chance of your info being revealed, do not
        join nets. You can find out whether a room you intend to join is a net
        or not by running `=info <room name>`.
        """
        if ctx.author.voice is None:
            await ctx.send("You're not in a voice channel!")
            return
        if ctx.guild.voice_client is not None:
            await ctx.send('Already in a voice channel!')
            return
        channel = ctx.author.voice.channel
        try:
            vc = await channel.connect()
        except discord.Forbidden:
            await ctx.send("Couldn't join your voice channel.")
            return
        wav = Wave(random.randint(220, 880))
        wav.muted = True
        def after(exc):
            if exc:
                traceback.print_exception(type(exc), exc, exc.__traceback__)
        try:
            vc.play(wav, after=after)
        except discord.Forbidden:
            await ctx.send("Can't speak in your voice channel.")
            await vc.disconnect()
            return
        _room = room
        if room not in rooms:
            rooms[room] = Room(room, keyed, net, password)
            if rooms[room].net and password:
                await ctx.send('Please DM me the new password for this net.')
                msg = await client.wait_for('message', check=lambda m: (
                    isinstance(m.channel, discord.DMChannel)
                    and m.author.id == ctx.author.id
                ))
                rooms[room].password = msg.content
        room = rooms[room]
        if room.net and room.password:
            pswd = ''
            tries = 3
            while pswd != room.password and tries > 0:
                await ctx.send('Please DM me the password for this net.')
                msg = await client.wait_for('message', check=lambda m: (
                    isinstance(m.channel, discord.DMChannel)
                    and m.author.id == ctx.author.id
                ))
                pswd = msg.content
                tries -= 1
            if pswd == room.password:
                pass
            else:
                await ctx.send("You didn't get the password right in three \
tries! Please try again later.")
                return
        await asyncio.sleep(1.5) # wait a bit because it takes a bit to start
        fut = client.loop.create_future()
        @client.listen()
        async def on_message(m):
            if m.channel.id != ctx.channel.id:
                return
            if m.content.startswith('='):
                return
            room.messages.put_nowait((ctx, m))
        await room.connect(ctx, wav, fut)
        await fut
        client.remove_listener(on_message)
        vc.stop()
        await vc.disconnect()
        if await room.disconnect(ctx):
            del rooms[_room]
        await ctx.send('Goodbye.')

    @commands.command()
    async def morse(self, ctx, *, text):
        """Convert text to Morse code."""
        await ctx.send(morse_msg(text) + ' ' + ctx.author.mention)

    @commands.command()
    async def info(self, ctx, *, room):
        """Get information about a room."""
        try:
            room = rooms[room]
        except KeyError:
            await ctx.send('No room named `%s`' % room)
            return
        embed = discord.Embed(title='Information on `%s`' % room.name)
        embed.add_field(name='Keyed', value='Yes' if room.keyed else 'No')
        embed.add_field(name='Net', value='Yes' if room.net else 'No')
        if room.net:
            embed.add_field(name='Password protected',
                            value='Yes' if room.password else 'No')
            embed.add_field(name='Current host', value=str(room.host.author))
            embed.set_footer(text='If you become the host of a net, your \
username and discriminator will be revealed to all users of the net at that \
moment. You could involuntarily become the host of the net if the host leaves, \
so if you want no chance of your information being leaked, do not join nets.')
        await ctx.send(embed=embed)

with open('morse.txt') as f:
    token = f.read().strip()

@tasks.loop(minutes=5.0)
async def set_playing_status():
    await client.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name='=help'
    ))

@set_playing_status.before_loop
async def before_playing():
    await client.wait_until_ready()

try:
    client.run(token)
except KeyboardInterrupt:
    pass
