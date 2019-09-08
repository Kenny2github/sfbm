import time
import random
import itertools
import traceback
import asyncio
import discord
import discord.opus
from discord.ext import commands

client = commands.Bot('=', description='Communicate with Morse code')

def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ')

@client.before_invoke
async def before_invoke(ctx):
    print(now(), ctx.author, 'ran', ctx.prefix + str(ctx.command))

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
    muted = False

    def __init__(self, freq=440):
        self.freq = self._freq = freq
        self.wav = self.wave()

    def wave(self):
        return ((i % int(FREQ / self.freq) / FREQ) for i in itertools.count())

    def read(self):
        if self.muted:
            return b'\0' * 3840
        samples = itertools.islice(self.wav, int(0.02 * FREQ))
        return b''.join(
            int(i * 32767 + 32768).to_bytes(2, 'big') * 2
            for i in samples
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

def mute(sources, yes):
    for r in sources:
        r.muted = yes

async def play_morse(msg, sources, wpm, freq):
    ditlength = 6/(5 * max(15, wpm))
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
    for r in sources:
        r.freq = freq
    for i in msg:
        if i == '.':
            mute(sources, False)
            await asyncio.sleep(ditlength)
        if i == '-':
            mute(sources, False)
            await asyncio.sleep(ditlength * 3)
        if i == '_':
            mute(sources, True)
            await asyncio.sleep(ditlength)
        if i == ' ':
            mute(sources, True)
            await asyncio.sleep(18 / (5 * wpm))
        if i == '/':
            mute(sources, True)
            await asyncio.sleep(42 / (5 * wpm))
    mute(sources, True)
    for r in sources:
        r.freq = r._freq

class Room:
    """Represents a Morse room."""
    def __init__(self, name, wpm=15, net=False, password=None):
        self.name = name
        self.wpm = wpm
        self.net = net
        self.password = password
        self.wavs = {}
        self.futs = {}
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
                if msg.content == 'done':
                    if msg.author.id != ctx.author.id:
                        continue
                    print(now(), ctx.author, 'ran', msg.content)
                    await self.set_speaker(ctx)
                    continue
                if msg.content.startswith('wpm'):
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
                if not msg.content.startswith(('.', '-')):
                    continue
                if self.net and not msg.author.id == ctx.author.id:
                    continue
                await self.speak(msg.content, self.wavs[ctx], self.wpms[ctx])
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            return
        except:
            traceback.print_exc()

    async def connect(self, ctx, wav, fut, wpm):
        """Connects the wave to the room. Returns whether you are the host."""
        self.wavs[ctx] = wav
        self.futs[ctx] = fut
        self.wpms[ctx] = wpm
        morsing = asyncio.create_task(play_morse(
            morse_msg(self.name), [wav], 30, 440
        ))
        if self.net:
            await ctx.send(f"""Joined your voice channel.
You are connected to **net** `{self.name}`.
Wait until you are allowed to speak.
Once you may, send `-- --- .-. ... . / -.-. --- -.. .`
to play it to all connected users.""")
            if len(self.wavs) == 1:
                await self.set_host(ctx)
                await self.set_speaking(ctx)
                await morsing
                return True
            self.new_users.add(ctx)
            await ctx.send(f'The net host is {self.host.author!s} \
({self.call(self.host)}). Feel free to DM them with any concerns.')
            await self.host.send(f'{self.call(ctx)} just joined the net! Run \
`welcome` to process automatic welcomes.')
        else:
            await ctx.send(f"""Joined your voice channel.
You are connected to room `{self.name}`.
Send `-- --- .-. ... . / -.-. --- -.. .`
to play it to all connected users in the room.""")
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

    async def welcome(self):
        """Starts welcoming new users."""
        if not self.net:
            return
        orig_speaking = self.speaking
        self.speaking = None
        await self.speak(morse_msg('Welcome:'), None, freq=440)
        await asyncio.sleep(0.5)
        for i in self.new_users:
            await self.speak(
                morse_msg(self.call(i)),
                None, freq=440
            )
            await asyncio.sleep(0.5)
        self.speaking = orig_speaking
        self.new_users.clear()

    async def speak(self, content, wav, wpm=None, freq=None):
        """Speaks content in Morse. If not allowed to speak, fails silently."""
        if self.net and self.wavs.get(self.speaking, None) != wav:
            return
        await play_morse(
            content,
            list(self.wavs.values()),
            wpm or self.wpm,
            freq or wav._freq
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
        if content.startswith('net wpm'):
            print(now(), ctx.author, 'ran', msg.content)
            try:
                self.wpm = int(content.split(' ')[-1])
            except ValueError:
                pass
            await ctx.send('Net WPM set to ' + str(self.wpm))
            return True
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
        if content.startswith('welcome'):
            print(now(), ctx.author, 'ran', msg.content)
            await ctx.send('Welcoming new users')
            old_wpm = self.wpm
            if content != 'welcome':
                try:
                    self.wpm = int(content.split()[-1])
                except ValueError:
                    return True
            await self.welcome()
            self.wpm = old_wpm
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
        self, ctx, room, wpm: int = 15,
        net: bool = False, password: bool = False
    ):
        """Join or create a room and send Morse. PLEASE RUN `=help join`

        If the room does not exist, it will be created. Send a message
        consisting solely of Morse code (or at least starting with a . or -) to
        interpret the message as Morse and send it at your WPM. Because the bot
        can only connect to one voice channel per server, anyone can join the
        voice channel with the bot and send Morse (unless the room is a net - if
        that is the case, others can only listen in); however, only the user who
        joined the bot to the voice channel may use "transient commands":

        done: transfers speaking privileges back to the host
        wpm <N>: changes the transmit WPM to N.
        bye: disconnects the bot

        Nets are a more formal type of room where one person (the host) decides
        who is allowed to speak at any given moment. This is useful for large
        rooms where it would be too chaotic if everyone were to speak at once.
        Only the host of a net may use the following transient commands:

        net wpm <N>: changes the WPM for automatic welcome messages.
        host <callsign>: transfers hosting privileges to the specified user
        speaker <callsign>: transfers speaking privileges to the specified user
        welcome [WPM]: starts the process of automatically welcoming users who
            have joined since the last welcome, optionally at WPM WPM
        users: returns a list of callsigns connected to the net

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
        try:
            vc.play(wav)
        except discord.Forbidden:
            await ctx.send("Can't speak in your voice channel.")
            await vc.disconnect()
            return
        _room = room
        if room not in rooms:
            rooms[room] = Room(room, wpm, net, password)
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
        await room.connect(ctx, wav, fut, wpm)
        await fut
        client.remove_listener('message', on_message)
        vc.stop()
        await vc.disconnect()
        if await room.disconnect(ctx):
            del rooms[_room]
        await ctx.send('Goodbye.')

    @commands.command()
    async def morse(self, ctx, *, text):
        """Convert text to Morse code."""
        await ctx.send(morse_msg(text))

    @commands.command()
    async def info(self, ctx, *, room):
        """Get information about a room."""
        try:
            room = rooms[room]
        except KeyError:
            await ctx.send('No room named `%s`' % room)
            return
        embed = discord.Embed(title='Information on `%s`' % room.name)
        embed.add_field(name='WPM', value=room.wpm)
        embed.add_field(name='Net', value='Yes' if room.net else 'No')
        embed.add_field(name='Password protected',
                        value='Yes' if room.password else 'No')
        embed.add_field(name='Current host', value=str(room.host.author))
        if room.net:
            embed.set_footer(text='If you become the host of a net, your \
username and discriminator will be revealed to all users of the net at that \
moment. You could involuntarily become the host of the net if the host leaves, \
so if you want no chance of your information being leaked, do not join nets.')
        await ctx.send(embed=embed)

client.add_cog(Morse())

with open('morse.txt') as f:
    token = f.read().strip()

async def wakeup():
    try:
        while 1:
            await asyncio.sleep(1)
    except:
        return
try:
    task = client.loop.create_task(client.start(token))
    client.loop.run_until_complete(wakeup())
except KeyboardInterrupt:
    client.loop.run_until_complete(client.logout())
finally:
    client.loop.close()
