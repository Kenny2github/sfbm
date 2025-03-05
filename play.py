import sys
from dataclasses import dataclass, field
import math
from queue import Empty, SimpleQueue
from typing import Callable, TypeVar

import discord

FREQ = 48000 # Hz
FRAME = 20 # ms

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

def morse_msg(msg: str) -> str:
    return ' '.join(MORSE.get(i, '..--..') for i in msg.lower())

def sawtooth(freq: float, phase: float) -> float:
    return (phase % freq) / freq * 2 - 1

def sine(freq: float, phase: float) -> float:
    return math.sin(2 * math.pi * phase / freq)

T = TypeVar('T')
D = TypeVar('D')
def get_or(queue: SimpleQueue[T], default: D = None) -> T | D:
    try:
        return queue.get(block=False)
    except Empty:
        return default

@dataclass
class Wave(discord.AudioSource):

    sample_rate: int = FREQ
    waveform: Callable[[float, float], float] = field(default=sawtooth)
    frames: dict[float, SimpleQueue[bool]] = field(default_factory=dict)

    phase: int = 0

    def read(self):
        # one frame of audio
        samples = int(self.sample_rate * FRAME / 1000)
        self.phase += samples
        # get one frame of frequency data
        freqs = {freq for freq, queue in self.frames.items() if get_or(queue, False)}
        return b''.join(
            int(
                # generate frame of wave based on frequency and phase
                sum(self.waveform(self.sample_rate / f, i + self.phase) for f in freqs)
                # attenuate based on number of waves present
                / (len(freqs) or 1)
                # convert float wave frame to 16-bit int
                * 32767
            # double for left and right stereo channels
            ).to_bytes(2, sys.byteorder, signed=True) * 2
            for i in range(samples)
        )

    def queue_morse(self, msg: str, wpm: int, freq: float) -> str:
        ditlength = 6000 // (5 * max(15, wpm)) // FRAME # in frames
        pauselength = 6000 // (5 * wpm) // FRAME # in frames
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
        for c in msg:
            frame = {
                '.': {freq},
                '-': {freq},
                '_': {},
                ' ': {},
                '/': {},
            }[c]
            length = {
                '.': ditlength,
                '-': ditlength * 3,
                '_': ditlength,
                ' ': pauselength * 3,
                '/': pauselength * 7,
            }[c]
            for _ in range(length):
                self.frames.setdefault(freq, SimpleQueue()).put(frame)
        return msg

    def queue_text(self, msg: str, wpm: int, freq: float) -> str:
        return self.queue_morse(morse_msg(msg), wpm, freq)
