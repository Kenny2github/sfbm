from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, overload
import discord

if TYPE_CHECKING:
    from view import RoomView

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

@dataclass
class Room:
    name: str
    net: bool = False
    access_key: str | None = None
    _host: Call | None = field(init=False, default=None)
    _speaking: Call | None = field(init=False, default=None)
    views: set[RoomView] = field(init=False, default_factory=set)

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
