from math import sin, pi
import itertools
import asyncio
import discord
import discord.opus
from discord.ext import commands

client = commands.Bot(description='Communicate with Morse code', command_prefix=['.', '-'])

FREQ = 48000

class SineWave(discord.AudioSource):
    frame = 0
    freq = 440
    def __init__(self, freq=440):
        self.freq = freq
        self.wav = self.wave()

    def wave(self):
        period = int(FREQ / self.freq)
        lookup = [sin(2 * pi * self.freq * (i % period) / FREQ) for i in range(period)]
        return (lookup[i % period] for i in itertools.count())

    def read(self):
        samples = itertools.islice(self.wav, int(0.02 * FREQ))
        return b''.join(int(i * 32767 + 32768).to_bytes(2, 'big') * 2 for i in samples)

@client.command()
async def join(ctx):
    if ctx.author.voice is None:
        await ctx.send("You're not in a voice channel!")
    channel = ctx.author.voice.channel
    vclient = await channel.connect()
    vclient.play(SineWave(), after = lambda exc: print(type(exc).__name__, exc))

@client.command()
async def leave(ctx):
    guild = ctx.guild
    for i in client.voice_clients:
        if i.guild.id == guild.id:
            i.stop()
            await i.disconnect()
            break

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
