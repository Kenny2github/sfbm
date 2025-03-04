# Samuel F. B. Morse

Talk to people in other servers via Morse code.

## Link to Add
https://discord.com/api/oauth2/authorize?client_id=619145918733746176&permissions=36784192&scope=bot+applications.commands

## Prefix
`=`

## Usage
PLEASE RUN `=help join`; below is the quick-and-dirty flow.

1. Join a voice channel.
2. `=join <room name> [keyed? yes or no] [net? yes or no] [password? yes or no]` - the bot will join your voice channel and connect you to that room.
3. If `keyed` was yes, use your PTT button as a keyer; otherwise, send Morse code into the channel e.g. `.... . .-.. .-.. --- / .-- --- .-. .-.. -.. ..--.`
4. The bot will play back any Morse received from other ends.
5. If `keyed` was no and you want to change the WPM the bot plays your Morse at, send `wpm N` where N is the number.
6. If you want to leave, send `bye`.

This is sort of hyper-QSK because you can receive while you're typing and transmitting as well.
