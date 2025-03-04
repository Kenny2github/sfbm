from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import overload
import discord

from play import Wave

Call = tuple[discord.Guild, discord.User | discord.Member]

@overload
def callsign(guild_id: int, user_id: int, /) -> str: ...
@overload
def callsign(call: Call, /) -> str: ...

def callsign(guild_id_or_call: int | Call, user_id: int | None = None, /) -> str:
    if isinstance(guild_id_or_call, int):
        assert user_id is not None
        guild = str(guild_id_or_call)
        user = str(user_id)
    else:
        guild, user = guild_id_or_call
        guild = str(guild.id)
        user = str(user.id)
    return (
        chr(65 + int(guild[-2:]) % 26)
        + chr(65 + int(guild[-4:-2]) % 26)
        + guild[1]
        + chr(65 + int(user[-2:]) % 26)
        + chr(65 + int(user[-4:-2]) % 26)
        + chr(65 + int(user[-6:-4]) % 26)
    )

class SingleValueModal(discord.ui.Modal):

    body: discord.ui.TextInput
    room: Room
    view: RoomView
    title: str
    label: str
    style: discord.TextStyle = discord.TextStyle.short
    placeholder: str | None = None

    def __init__(self, *, room: Room, view: RoomView) -> None:
        super().__init__(title=self.title, timeout=5 * 60)
        self.body = discord.ui.TextInput(
            label=self.label,
            style=self.style,
            placeholder=self.placeholder
        )
        self.add_item(self.body)
        self.room = room
        self.view = view

class MorseModal(SingleValueModal):

    title = 'Send Morse'
    label = 'Morse code to send'
    style = discord.TextStyle.paragraph
    placeholder = '-- --- .-. ... . / -.-. --- -.. .'

    async def on_submit(self, ctx: discord.Interaction) -> None:
        if not self.room.views:
            await ctx.response.send_message('No one is here', ephemeral=True)
            return
        for view in self.room.views:
            _, user = view.user
            msg = view.audio.queue_morse(self.body.value, view.wpm,
                                         (user.id % 100) + 300)
        await ctx.response.edit_message()

class TextModal(SingleValueModal):

    title = 'Send Text'
    label = 'Text to send'
    style = discord.TextStyle.paragraph
    placeholder = 'Regular text'

    async def on_submit(self, ctx: discord.Interaction) -> None:
        if not self.room.views:
            await ctx.response.send_message('No one is here', ephemeral=True)
            return
        for view in self.room.views:
            _, user = view.user
            msg = view.audio.queue_text(self.body.value, view.wpm,
                                        (user.id % 100) + 300)
        await ctx.response.edit_message()

class WPMModal(SingleValueModal):

    title = 'Set WPM'
    label = 'Words per minute'
    placeholder = '15'

    async def on_submit(self, ctx: discord.Interaction) -> None:
        try:
            wpm = int(self.body.value)
        except ValueError:
            await ctx.response.send_message(f'Invalid WPM: {self.body.value!r}', ephemeral=True)
            return
        self.view.wpm = wpm
        await ctx.response.edit_message(embed=self.view.make_embed())

class CallsignModal(SingleValueModal):

    label = 'Callsign'
    placeholder = 'XO3ZOO'

    def __init__(self, *, room: Room, view: RoomView, label: str) -> None:
        self.title = 'Set ' + label.title()
        super().__init__(room=room, view=view)
        self.attr = label.casefold()

    async def on_submit(self, ctx: discord.Interaction) -> None:
        call = self.body.value.strip().upper()
        for view in self.room.views:
            if callsign(view.user) == call:
                result = view
                break
        else:
            await ctx.response.send_message(f'No such callsign {call!r}', ephemeral=True)
            return
        setattr(self.room, self.attr, result.user)
        await ctx.response.edit_message()

@dataclass
class Room:
    name: str
    net: bool = False
    password: str | None = None
    _host: Call | None = None
    _speaking: Call | None = None
    views: set[RoomView] = field(default_factory=set)

    @property
    def host(self) -> Call | None:
        return self._host

    @host.setter
    def host(self, value: Call | None) -> None:
        self._host = value
        self.update_views()

    @property
    def speaking(self) -> Call | None:
        return self._speaking

    @speaking.setter
    def speaking(self, value: Call | None) -> None:
        self._speaking = value
        self.update_views()

    def update_views(self) -> None:
        for view in self.views:
            asyncio.create_task(view.send_update())

class RoomView(discord.ui.View):

    msg: discord.Message | discord.PartialMessage
    room: Room
    audio: Wave
    user: Call
    wpm: int = 15

    def __init__(self, *, msg: discord.Message | discord.PartialMessage, room: Room, audio: Wave, user: Call):
        super().__init__(timeout=None)
        self.msg = msg
        self.room = room
        self.audio = audio
        self.user = user
        if not self.room.net:
            self.remove_item(self.host)
            self.remove_item(self.speak)
            self.remove_item(self.done)
        self.update()

    def update(self) -> None:
        if self.room.host:
            self.host.disabled = self.speak.disabled = self.user[1] != self.room.host[1]
            self.text.disabled = self.morse.disabled = self.done.disabled = self.room.speaking is None or self.user[1] != self.room.speaking[1]
            self.done.disabled = self.done.disabled or not self.speak.disabled

    def make_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f'Connected to room `{self.room.name}`',
            description=f'Your callsign is `{callsign(self.user)}`',
        )
        embed.add_field(name='WPM', value=str(self.wpm))
        if self.room.host:
            guild, user = self.room.host
            embed.add_field(name='Net Control', value=callsign(guild.id, user.id))
        if self.room.speaking:
            guild, user = self.room.speaking
            embed.add_field(name='Currently Speaking', value=callsign(guild.id, user.id))
        return embed

    async def send_update(self) -> None:
        self.update()
        await self.msg.edit(embed=self.make_embed(), view=self)

    @discord.ui.button(
        label='Text',
        style=discord.ButtonStyle.primary,
    )
    async def text(self, ctx: discord.Interaction,
                   button: discord.ui.Button) -> None:
        await ctx.response.send_modal(TextModal(room=self.room, view=self))

    @discord.ui.button(
        label='Morse',
        style=discord.ButtonStyle.primary,
    )
    async def morse(self, ctx: discord.Interaction,
                    button: discord.ui.Button) -> None:
        await ctx.response.send_modal(MorseModal(room=self.room, view=self))

    @discord.ui.button(
        label='Set WPM',
        style=discord.ButtonStyle.secondary,
    )
    async def set_wpm(self, ctx: discord.Interaction,
                      button: discord.ui.Button) -> None:
        await ctx.response.send_modal(WPMModal(room=self.room, view=self))

    @discord.ui.button(
        label='Users',
        style=discord.ButtonStyle.secondary,
    )
    async def users(self, ctx: discord.Interaction,
                    button: discord.ui.Button) -> None:
        await ctx.response.send_message('\n'.join(callsign(view.user) for view in self.room.views), ephemeral=True)

    @discord.ui.button(
        label='Leave',
        style=discord.ButtonStyle.danger,
    )
    async def leave(self, ctx: discord.Interaction,
                    button: discord.ui.Button) -> None:
        self.room.views.remove(self)
        await ctx.response.edit_message(view=None)
        await ctx.followup.send('Goodbye', ephemeral=True)
        self.stop()
        if not self.room.views:
            return
        if self.room.host == self.user:
            self.room.host = next(iter(self.room.views)).user
        if self.room.speaking == self.user:
            self.room.speaking = self.room.host

    @discord.ui.button(
        label='Done Speaking',
        style=discord.ButtonStyle.success,
    )
    async def done(self, ctx: discord.Interaction,
                   button: discord.ui.Button) -> None:
        self.room.speaking = self.room.host
        await ctx.response.edit_message()

    @discord.ui.button(
        label='Change Host',
        style=discord.ButtonStyle.danger,
        disabled=True,
    )
    async def host(self, ctx: discord.Interaction,
                   button: discord.ui.Button) -> None:
        await ctx.response.send_modal(CallsignModal(room=self.room, view=self, label='host'))

    @discord.ui.button(
        label='Set Speaking',
        style=discord.ButtonStyle.secondary,
        disabled=True,
    )
    async def speak(self, ctx: discord.Interaction,
                    button: discord.ui.Button) -> None:
        await ctx.response.send_modal(CallsignModal(room=self.room, view=self, label='speaking'))
