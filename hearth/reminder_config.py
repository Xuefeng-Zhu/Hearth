import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .storage import HearthError, atomic_write

CHANNELS = {"app": ("app",), "email": ("email",), "both": ("app", "email")}
KINDS = ("reminder", "event", "receipt", "person", "list", "other")
NOT_CONNECTED = "Not connected — add AgentMail in Fly connectors (Name Prefix hearth)"
DEFAULTS = {"channel": "app", "recipient": "", "quiet_start": "22:00", "quiet_end": "07:00",
            "timezone": "America/Los_Angeles", "allowed_senders": [], "auto_accept": [], "acknowledge": False}
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def address(value):
    if isinstance(value, str) and len(value) <= 254 and EMAIL.fullmatch(value):
        return value.lower()
    return ""


def settings(value):
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise HearthError("Invalid reminder settings.")
    data = {**DEFAULTS, **value}
    for key in ("channel", "recipient", "quiet_start", "quiet_end", "timezone"):
        if not isinstance(data[key], str):
            raise HearthError("Invalid reminder settings.")
        data[key] = data[key].strip()
    if data["channel"] not in CHANNELS or (data["recipient"] and not address(data["recipient"])):
        raise HearthError("Choose a channel and enter a valid recipient email.")
    if not all(CLOCK.fullmatch(data[key]) for key in ("quiet_start", "quiet_end")):
        raise HearthError("Enter quiet hours as HH:MM.")
    try:
        ZoneInfo(data["timezone"])
    except (ValueError, ZoneInfoNotFoundError):
        raise HearthError("Use an IANA time zone such as America/Los_Angeles.") from None
    senders, kinds = data["allowed_senders"], data["auto_accept"]
    if (not isinstance(senders, list) or len(senders) > 100 or not all(map(address, senders))
            or not isinstance(kinds, list) or not all(kind in KINDS for kind in kinds)
            or type(data["acknowledge"]) is not bool):
        raise HearthError("Enter complete allowed sender email addresses and valid proposal types.")
    return {**data, "allowed_senders": sorted(set(map(address, senders))), "auto_accept": sorted(set(kinds))}


def saved(state):
    return {**DEFAULTS, **state.get("reminder_settings", {})}


def channel_from_prompt(prompt):
    if re.search(r"\b(?:both channels|(?:in[- ]app|in (?:the )?app) and (?:by )?(?:e-?mail)|e-?mail and (?:in[- ]app|in (?:the )?app))\b", prompt, re.I):
        return "both"
    if re.search(r"\b(?:by|via|over) e-?mail\b|\be-?mail (?:me )?(?:a|the) reminder\b", prompt, re.I):
        return "email"
    if re.search(r"\bin[- ]app\b|\bin (?:the )?app\b", prompt, re.I):
        return "app"
    return None


def quiet_until(now, config):
    local = now.astimezone(ZoneInfo(config["timezone"]))
    start, end = config["quiet_start"], config["quiet_end"]
    current = local.strftime("%H:%M")
    if start == end or not (start <= current < end if start < end else current >= start or current < end):
        return None
    day = local.date() + timedelta(days=int(start > end and current >= start))
    target = datetime.combine(day, datetime.strptime(end, "%H:%M").time(), local.tzinfo)
    # During a repeated hour, use the later end. During a skipped hour, convert forward.
    return max(target.astimezone(timezone.utc), target.replace(fold=1).astimezone(timezone.utc))


def secret(storage, name):
    path = storage.root / name
    with storage.lock():
        if not path.is_file():
            atomic_write(path, secrets.token_urlsafe(32))
        return path.read_text(encoding="utf-8").strip()


def equal(left, right):
    return isinstance(left, str) and hmac.compare_digest(left.encode(), right.encode())


def public_url(value):
    if value:
        try:
            url = urlsplit(value)
            if (url.scheme == "https" and url.netloc == url.hostname and url.hostname.endswith(".sprites.app")
                    and url.path in ("", "/") and not (url.query or url.fragment)):
                return value.rstrip("/")
        except (AttributeError, ValueError):
            pass
    return ""
