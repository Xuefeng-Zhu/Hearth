"""Literal Unicode search and text fragments for safe highlighting."""

import unicodedata

from .storage import HearthError


def fold(text):
    return "".join(char for char in unicodedata.normalize("NFD", text.casefold())
                   if not unicodedata.category(char).startswith("M"))


def snippet(text, query, *, excerpt=True):
    folded = []
    offsets = []
    for index, char in enumerate(text):
        piece = fold(char)
        folded.append(piece)
        offsets.extend([index] * len(piece))
    normalized = "".join(folded)
    first = normalized.index(query)
    start, end = 0, len(text)
    if excerpt:
        start = max(0, offsets[first] - 55)
        end = min(end, max(start + 165, offsets[first + len(query) - 1] + 56))
    parts = [{"text": "…"}] if start else []
    tail = start
    while first >= 0 and offsets[first] < end:
        left = max(offsets[first], tail)
        last = first + len(query)
        right = offsets[last - 1] + 1
        while right < len(text) and unicodedata.category(text[right]).startswith("M"):
            right += 1
        right = min(right, end)
        if left > tail:
            parts.append({"text": text[tail:left]})
        if right > left:
            parts.append({"text": text[left:right], "match": True})
            tail = right
        first = normalized.find(query, last)
    if tail < end or end < len(text):
        parts.append({"text": text[tail:end] + ("…" if end < len(text) else "")})
    return parts


def list_query(params):
    values = params.get("q")
    if values is None:
        return None
    if len(values) != 1 or not 1 <= len(values[0].strip()) <= 200 or "\x00" in values[0]:
        raise HearthError("Enter a search query between 1 and 200 characters.")
    return fold(values[0].strip())


def match_row(row, query, fields, extra=()):
    if not query:
        return None

    def match(value, *, excerpt):
        if query in fold(value):
            return snippet(value, query, excerpt=excerpt)
        if excerpt:
            text = " ".join(value.split())
            if text != value and query in fold(text):
                return snippet(text, query)

    matches = {}
    for key, value in fields.items():
        if value and (parts := match(value, excerpt=False)):
            matches[key] = parts
    if matches:
        return {**row, "search_matches": matches}
    for value in extra:
        if value and (parts := match(value, excerpt=True)):
            return {**row, "search_matches": {"excerpt": parts}}
    return None
