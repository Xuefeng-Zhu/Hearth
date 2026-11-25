import re
from urllib.parse import urlsplit

from .connectors import ConnectorError
from .gateway_tools import redact_text
from .storage import HearthError
from .threads import compact
from .voice import VoiceError

PROVIDER = "vocalbridge"
SOURCE = "voice-call"
TOKEN_PATH = "api/v1/token"
SETUP = "Add Vocal Bridge in Fly dashboard with Name Prefix hearth."
MAX_REPORT_BYTES = 512 * 1024
MAX_LINES = 400
MAX_SECONDS = 60 * 60


def participant_name(storage):
    with storage.lock():
        try:
            profile = storage.read("USER.md")
        except (HearthError, OSError):
            return "User"
    if heading := re.search(r"^# ([^\n]+)", profile, re.M):
        return compact(redact_text(heading[1]), 64) or "User"
    return "User"


def mint(gateway, connection, name):
    try:
        reply = gateway.json(connection, TOKEN_PATH, {"participant_name": name}, timeout=115)
    except ConnectorError as error:
        if error.status in (408, 504):
            raise VoiceError("The Fly gateway timed out while starting the call. Try again.", 504) from None
        if error.status in (404, 409):
            raise VoiceError("The Vocal Bridge agent is unavailable. Deploy the agent for this key and try again.", 503) from None
        if error.status in (402, 403):
            raise VoiceError("Vocal Bridge denied the call. Check available voice usage and the connector’s access in Fly.", 403) from None
        if error.status == 401:
            raise VoiceError("Vocal Bridge rejected the connection. Check the agent-scoped key in Fly.", 502) from None
        if error.status == 429:
            raise VoiceError("Vocal Bridge is rate-limiting calls. Check available usage or try again shortly.", 429) from None
        raise VoiceError("Hearth could not start a Vocal Bridge call through Fly.", 502) from None

    url = reply.get("url") or reply.get("livekit_url")
    token, room, expiry = (reply.get(key) for key in ("token", "room_name", "expires_in"))
    try:
        address = urlsplit(url) if isinstance(url, str) else None
        valid_url = (address and address.scheme == "wss" and address.hostname
                     and address.hostname.endswith(".livekit.cloud")
                     and address.port in (443, None)
                     and not (address.username or address.password or address.query or address.fragment))
    except ValueError:
        valid_url = False
    if (not valid_url or not isinstance(token, str) or not token.strip()
            or not isinstance(room, str) or not room.strip() or type(expiry) is not int or expiry <= 0):
        raise VoiceError("Vocal Bridge returned incomplete session credentials.", 502)
    return {"url": url, "token": token, "room_name": room, "expires_in": expiry}


def save_report(threads, body):
    if body.keys() != {"id", "thread_id", "duration", "demo", "lines"}:
        raise HearthError("Invalid call summary.")
    identity, thread, seconds, demo, entries = (body[key] for key in ("id", "thread_id", "duration", "demo", "lines"))
    if (not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity)
            or type(seconds) is not int or not 0 <= seconds <= MAX_SECONDS or type(demo) is not bool
            or not isinstance(entries, list) or len(entries) > MAX_LINES):
        raise HearthError("Invalid call summary.")
    lines = []
    for entry in entries:
        if (not isinstance(entry, dict) or entry.get("role") not in ("user", "agent")
                or not isinstance(entry.get("text"), str) or len(entry["text"]) > 4_000):
            raise HearthError("Invalid call transcript.")
        if text := redact_text(entry["text"].strip()):
            lines.append({"role": entry["role"], "text": text})
    with threads.storage.lock():
        for message in reversed(threads.messages(thread)):
            if message.get("id") == identity and message["role"] == "call":
                return message
        return threads.append(thread, "call", "Demo voice call" if demo else "Voice call", id=identity,
                              source=SOURCE, duration=seconds, demo=demo, lines=lines)
