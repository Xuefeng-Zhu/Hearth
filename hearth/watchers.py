"""Read-only monitoring for public pages the user approves."""

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from . import browserbase, panels
from .storage import HearthError

MODES = ("price", "page")
AMOUNT = r"\d{1,3}(?:[ ,.]\d{3})+(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?"
PRICE = re.compile(rf"(?:\b(?:USD|EUR|GBP|CAD|AUD)\s*|[$€£]\s*)(?:{AMOUNT})(?![\d.,]\d)")


def public_url(value):
    url = browserbase.page_url(value)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.query or parsed.fragment:
        raise HearthError("Choose a public HTTPS page link without a query or fragment.")
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", "", ""))


def clean(watch):
    if not isinstance(watch, dict) or watch.keys() != {"url", "mode"} or watch["mode"] not in MODES:
        raise HearthError("Choose whether to watch prices or readable page text.")
    return {"url": public_url(watch["url"]), "mode": watch["mode"]}


def observe(watch):
    # Use the Home panel reader's pinned public DNS and bounded GET. Page text stays data.
    content = panels.public_page(watch["url"])
    values = []
    if watch["mode"] == "price":
        values = sorted({" ".join(match.split()) for match in PRICE.findall(content)})
        if not values:
            raise HearthError("The public page did not show readable prices.")
        content = "\n".join(values)
    return {"signature": hashlib.sha256(content.encode()).hexdigest(), "prices": values[:10]}


def report(watch, before, after):
    host = urlsplit(watch["url"]).hostname
    if watch["mode"] == "price":
        if before["prices"] == after["prices"]:
            return f"The list of displayed prices changed on {host}."
        return f"Displayed prices changed on {host}. Previously {', '.join(before['prices'])}. Now {', '.join(after['prices'])}."
    return f"The readable page text changed on {host}."
