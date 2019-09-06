import random
import itertools
import traceback
import asyncio
import discord
import discord.opus
from discord.ext import commands

client = commands.Bot(description='Communicate with Morse code', command_prefix='=')

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

async def play_morse(msg, sources, wpm, freq):
    ditlength = 6/(5 * 15)
    for r in sources:
        r.freq = freq
    for j in msg.split('/'):
        j = j.strip()
        for i in j:
            if i == '.':
                for r in sources:
                    r.muted = False
                await asyncio.sleep(ditlength)
                for r in sources:
                    r.muted = True
                await asyncio.sleep(ditlength)
            if i == '-':
                for r in sources:
                    r.muted = False
                await asyncio.sleep(ditlength * 3)
                for r in sources:
                    r.muted = True
                await asyncio.sleep(ditlength)
            if i == ' ':
                for r in sources:
                    r.muted = True
                await asyncio.sleep(12 / (5 * wpm))
        for r in sources:
            r.muted = True
        await asyncio.sleep(36 / (5 * wpm))
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
        self.speaking = None
        self.new_users = set()
        self.host = None

    async def connect(self, ctx, wav):
        """Connects the wave to the room. Returns whether you are the host."""
        self.wavs[ctx] = wav
        if self.net:
            await ctx.send(f"""Joined your voice channel.
You are connected to **net** `{self.name}`.
Wait until you are allowed to speak.
Once you may, send `-- --- .-. ... . / -.-. --- -.. .`
to play it to all connected users.""")
            if len(self.wavs) == 1:
                await self.set_host(ctx)
                await self.set_speaking(ctx)
                return True
            self.new_users.add(ctx)
            await ctx.send(f'The net host is {self.host.name}#\
{self.host.discriminator}. Feel free to DM them with any concerns.')
            await self.host.send(f'{ctx.author.name}#{ctx.author.discriminator}\
 just joined the net! Run `welcome` to process automatic welcomes.')
        else:
            await ctx.send(f"""Joined your voice channel.
You are connected to room `{self.name}`.
Send `-- --- .-. ... . / -.-. --- -.. .`
to play it to all connected users in the room.""")
        return False

    def disconnect(self, ctx):
        """Disconnects the wave from the room. Returns whether to destroy."""
        del self.wavs[ctx]
        if self.net:
            if self.host == ctx and len(self.wavs) > 1:
                self.host, self.wavs[self.host] = self.wavs.popitem()
        return len(self.wavs) <= 0

    async def welcome(self):
        """Starts welcoming new users."""
        if not self.net:
            return
        self.speaking = None
        await self.speak(morse_msg('Welcome: '), None)
        for i in self.new_users:
            await self.speak(
                morse_msg('{0.name} {0.discriminator}, '.format(i.author)),
                None
            )
        self.new_users.clear()

    async def speak(self, content, wav, wpm=None):
        """Speaks content in Morse. If not allowed to speak, fails silently."""
        if self.net:
            print(content, self.wavs.get(self.speaking, None), wav)
        if self.net and self.wavs.get(self.speaking, None) != wav:
            return
        await play_morse(
            content,
            list(self.wavs.values()),
            wpm or self.wpm,
            wav._freq
        )

    async def set_speaking(self, ctx):
        """Host-only: sets the user who may speak."""
        if self.speaking is not None:
            await self.speaking.send('The net host has decided that you may no longer speak.')
        self.speaking = ctx
        await ctx.send('The net host has decided that you may now speak.')

    async def set_host(self, ctx):
        """Host-only: sets the new host."""
        old_host = None
        if self.host is not None:
            old_host = self.host
            await self.host.send('You are no longer the host.')
        self.host = ctx
        await self.host.send('You are now the host of this net!')
        await asyncio.gather(*(i.send(f'{self.host.name}#\
{self.host.discriminator} is now the host of this net.') for i in self.wavs
if i != self.host and i != old_host))

    async def process_commands(self, content, ctx):
        """Process net commands. Returns whether to skip sending Morse."""
        if not self.net:
            return not content.startswith(('.', '-'))
        if ctx != self.host:
            return not content.startswith(('.', '-'))
        if content.startswith('net wpm'):
            try:
                self.wpm = int(content.split(' ')[-1])
            except ValueError:
                pass
            await ctx.send('Net WPM set to ' + str(self.wpm))
            return True
        if content.startswith('host'):
            try:
                name, discrim = content.split(' ')[-1].split('#')
            except TypeError:
                return True
            for c in self.wavs:
                if c.author.name == name and str(c.author.discriminator) == discrim:
                    self.set_host(c)
                    return True
            return True
        if content.startswith('speaker'):
            try:
                name, discrim = content.split(' ')[-1].split('#')
            except TypeError:
                return True
            for c in self.wavs:
                if c.author.name == name and str(c.author.discriminator) == discrim:
                    self.set_speaking(c)
                    await ctx.send('Speaking privileges transferred to %s#%s'
                                   % (name, discrim))
                    return True
            return True
        if content.startswith('welcome'):
            await ctx.send('Welcoming new users')
            await self.welcome()
            return True
        if content.startswith('users'):
            await ctx.send('\n'.join(
                '@{0.name}#{0.discriminator}'.format(i)
                for i in self.wavs
            ))
            return True
        return content.startswith(('.', '-'))

@client.command()
async def join(
    ctx, room, wpm: int = 15,
    net: bool = False, password: bool = False
):
    """Join or create a room and send Morse. PLEASE RUN `=help join`

    If the room does not exist, it will be created. Send a message consisting
    solely of Morse code (or at least starting with a . or -) to interpret the
    message as Morse and send it at your WPM. Because the bot can only connect
    to one voice channel per server, anyone can join the voice channel with the
    bot and send Morse; however, only the user who joined the bot to the voice
    channel may use "transient commands":

    wpm <N>: changes the transmit WPM to N.
    bye: disconnects the bot

    Nets are a more formal type of room where one person (the host) decides who
    is allowed to speak at any given moment. This is useful for large rooms
    where it would be too chaotic if everyone were to speak simultaneously.
    Only the host of a net may use the following transient commands:

    net wpm <N>: changes the WPM for automatic welcome messages.
    host <name#discrim>: transfers hosting privileges to the specified user
    speaker <name#discrim>: transfers speaking privileges to the specified user
    welcome: starts the process of automatically welcoming users who have joined
        since the last welcome
    users: returns a list of name#discrims connected to the net

    If `net` is true and the room did not previously exist, the room will be
    created as a net, with you as the host. If `password` is true, you will be
    asked to set the password for the net, and all people wanting to join the
    net will asked for the correct password. The host's name and discriminator
    are revealed to all users of the net AND all users who look up the net via
    `=info`, so if you don't want to reveal this, do not host a net.

    Regardless of whether `net` is true, if the room already exists and it is a
    net, your name and discriminator will be revealed to the host so that they
    can decide who speaks. Additionally, if the net regularly welcomes new
    users, your name and discriminator will be revealed to all users of the net
    at that moment. If you don't want to reveal this, do not join nets. You can
    find out whether a room you intend to join is a net or not by running
    `=info <room name>`.
    """
    if ctx.author.voice is None:
        await ctx.send("You're not in a voice channel!")
        return
    if ctx.guild.voice_client is not None:
        await ctx.send('Already in a voice channel!')
        return
    channel = ctx.author.voice.channel
    vc = await channel.connect()
    wav = Wave(random.randint(220, 880))
    wav.muted = True
    vc.play(wav, after = lambda exc: exc and print(type(exc).__name__, exc))
    _room = room
    if room not in rooms:
        rooms[room] = Room(room, wpm, net, password)
        if password:
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
            await ctx.send("You didn't get the password right in three tries! \
Please try again later.")
            return
    morse_hi = morse_msg(_room)
    await asyncio.sleep(1.5) # wait a bit because it takes a bit to get going
    morsing = asyncio.create_task(play_morse(morse_hi, [wav], 30, 440))
    hostq = await room.connect(ctx, wav)
    await morsing
    messages = asyncio.Queue()
    @client.listen()
    async def on_message(m):
        if m.channel.id != ctx.channel.id:
            return
        if m.content.startswith('='):
            return
        messages.put_nowait(m)
    while 1:
        if not vc.is_connected():
            break
        msg = await messages.get()
        if room.net and hostq and await room.process_commands(msg.content, ctx):
            continue
        if msg.content.startswith('wpm'):
            if msg.author.id != ctx.author.id:
                continue
            try:
                wpm = int(msg.content.split()[-1])
            except ValueError:
                continue
            await ctx.send('WPM set to %s' % wpm)
            continue
        if msg.content == 'bye':
            if msg.author.id != ctx.author.id:
                continue
            break
        if not msg.content.startswith(('.', '-')):
            continue
        await room.speak(msg.content, wav, wpm)
        await asyncio.sleep(1)
    client.remove_listener('message', on_message)
    vc.stop()
    await vc.disconnect()
    if room.disconnect(ctx):
        del rooms[_room]
    await ctx.send('Goodbye.')

@client.command()
async def morse(ctx, *, text):
    """Convert text to Morse code."""
    await ctx.send(morse_msg(text))

@client.command()
async def info(ctx, *, room):
    """Get information about a room."""
    try:
        room = rooms[room]
    except KeyError:
        await ctx.send('No room named `%s`' % room)
        return
    embed = discord.Embed(title='Information on `%s`' % room.name)
    embed.add_field(name='WPM', room.wpm)
    embed.add_field(name='Net', 'Yes' if room.net else 'No')
    embed.add_field(name='Password protected', 'Yes' if room.password else 'No')
    embed.add_field(name='Current host', '{0.name}#\
{0.discriminator}'.format(room.host))
    if room.net:
        embed.set_footer(text='By joining this net you may reveal your username\
 and discriminator to the host and other users of the net.')
    await ctx.send(embed=embed)

with open('morse.txt') as f:
    token = f.read().strip()

async def wakeup():
    try:
        while 1:
            await asyncio.sleep(1)
    except:
        return
try:
    wk = client.loop.create_task(wakeup())
    client.loop.run_until_complete(client.start(token))
except KeyboardInterrupt:
    client.loop.run_until_complete(client.logout())
    wk.cancel()
finally:
    client.loop.close()
