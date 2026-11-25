import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from .connectors import ConnectorError
from .gateway_tools import redact_text
from .storage import HearthError

PROVIDERS = ("tavily", "exa", "linkup", "kagi", "keenable", "firecrawl")
NATIVE_SAFE = {"tavily", "kagi", "keenable", "firecrawl"}
DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
DEFAULTS = {"provider": "auto", "max_results": 4, "recency": "any", "safe_search": False,
            "include_domains": [], "exclude_domains": []}
DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}")
EXPLICIT = re.compile(r"\b(?:porn(?:ography|ographic|hub)?|xxx|xvideos|xnxx|xhamster|onlyfans)\b", re.I)


def settings(values):
    if not isinstance(values, dict) or values.keys() - DEFAULTS.keys():
        raise HearthError("Invalid search settings.")
    result = {**DEFAULTS, **values}
    if (result["provider"] not in ("auto", "off", *PROVIDERS)
            or type(result["max_results"]) is not int or not 1 <= result["max_results"] <= 10
            or result["recency"] not in ("any", *DAYS) or type(result["safe_search"]) is not bool):
        raise HearthError("Choose a search provider, a result limit from 1–10, and a recency filter.")
    for key in ("include_domains", "exclude_domains"):
        domains = result[key]
        if not isinstance(domains, list) or len(domains) > 20 or any(
            not isinstance(domain, str) or len(domain) > 253 or not DOMAIN.fullmatch(domain.strip().lower())
            for domain in domains
        ):
            raise HearthError("Enter up to 20 domain names per list, without URLs or wildcards.")
        result[key] = list(dict.fromkeys(domain.strip().lower() for domain in domains))
    return result


def connected(config):
    entries = config.get("gateway", {})
    return {provider: entry for provider in PROVIDERS
            if (entry := entries.get(provider) or config.get(provider, {})).get("connection_id")}


def candidates(config, selection):
    entries = connected(config)
    provider = selection["provider"]
    order = PROVIDERS if provider == "auto" else (provider,)
    return [entries[slug] for slug in order if slug in entries]


def site_query(query, domains):
    if not domains:
        return query
    parts = " OR ".join(f"site:{domain}" for domain in domains)
    return f"{query} ({parts})"


def domain_options(include, exclude, include_key="includeDomains", exclude_key="excludeDomains"):
    return {key: domains for key, domains in ((include_key, include), (exclude_key, exclude)) if domains}


def adapter(provider, query, selection, cutoff):
    count = selection["max_results"]
    recency, safe = selection["recency"], selection["safe_search"]
    include, exclude = selection["include_domains"], selection["exclude_domains"]
    date = cutoff.isoformat() if cutoff else None
    if provider == "tavily":
        return "search", {"query": query, "max_results": count, "safe_search": safe,
                          **({"time_range": recency} if cutoff else {}),
                          **domain_options(include, exclude, "include_domains", "exclude_domains")}
    if provider == "exa":
        return "search", {"query": query, "numResults": count, "contents": {"highlights": {"maxCharacters": 650}},
                          **({"startPublishedDate": date + "T00:00:00Z"} if cutoff else {}),
                          **domain_options(include, exclude)}
    if provider == "linkup":
        return "v1/search", {"q": query, "depth": "standard", "outputType": "searchResults", "maxResults": count,
                             **({"fromDate": date} if cutoff else {}), **domain_options(include, exclude)}
    if provider == "kagi":
        return "api/v1/search", {"query": query, "limit": count,
                                 "filters": {"safe_search": safe, **({"after": date} if cutoff else {})},
                                 **({"lens": domain_options(include, exclude, "sites_included", "sites_excluded")}
                                    if include or exclude else {})}
    if provider == "keenable":
        return "v1/search", {"query": site_query(query, include) if len(include) > 1 else query,
                             "max_results": count, "snippet_max_length": 650, "disable_cards": True,
                             **({"site": include[0]} if len(include) == 1 else {}),
                             **({"exclude_domains": exclude} if exclude else {}),
                             **({"published_after": date} if cutoff else {}),
                             **({"moderation": "moderate"} if safe else {})}
    return "v2/search", {"query": query, "limit": count, "safe": safe,
                         **({"tbs": f"qdr:{recency[0]}"} if cutoff else {}),
                         **domain_options(include, [] if include else exclude)}


def rows_for(provider, data):
    if data.get("error") or data.get("errors") or data.get("success") is False:
        raise ConnectorError("The search provider reported an error.")
    if provider == "firecrawl":
        rows = data.get("data", {}).get("web") if isinstance(data.get("data"), dict) else None
    elif provider == "kagi":
        rows = data.get("data", {}).get("search") if isinstance(data.get("data"), dict) else data.get("data")
    else:
        rows = data.get("results")
    if not isinstance(rows, list):
        raise ConnectorError("The search provider returned an unexpected result format.")
    return rows


def clipped(value, limit):
    return redact_text(value).strip()[:limit] if isinstance(value, str) else ""


def matches(host, domains):
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def normalized_results(provider, data, selection, cutoff):
    seen = set()
    results = []
    for row in rows_for(provider, data):
        if not isinstance(row, dict):
            continue
        url = clipped(row.get("url"), 2_000)
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
        except ValueError:
            continue
        if parsed.scheme not in ("http", "https") or not host or parsed.username is not None or url in seen:
            continue
        if ((selection["include_domains"] and not matches(host, selection["include_domains"]))
                or matches(host, selection["exclude_domains"])):
            continue
        title = clipped(row.get("title") or row.get("name"), 220)
        highlights = row.get("highlights")
        snippet = clipped(row.get("snippet") or row.get("content") or row.get("description")
                          or (" ".join(s for s in highlights if isinstance(s, str)) if isinstance(highlights, list)
                              else row.get("text")), 650)
        published = clipped(row.get("published_date") or row.get("publishedDate") or row.get("published_at")
                            or row.get("publishedAt") or row.get("time") or row.get("date"), 65) or None
        if cutoff and published:
            try:
                if datetime.fromisoformat(published.replace("Z", "+00:00")).date() < cutoff:
                    continue
            except ValueError:
                pass  # Provider filters may return relative or localized date labels.
        if selection["safe_search"] and (row.get("nsfw") is True or EXPLICIT.search(f"{host} {title}")):
            continue
        seen.add(url)
        results.append({"title": title or host, "url": url, "snippet": snippet, "published": published})
        if len(results) >= selection["max_results"]:
            break
    return results


def search(gateway, config, selection, query, failure, *, preferred=None):
    start = time.monotonic()
    entries = candidates(config, selection)
    if preferred:
        entries.sort(key=lambda item: item["provider"] != preferred)
    if not entries:
        if selection["provider"] == "off":
            raise HearthError("Web search is off in Settings.")
        raise HearthError("No selected search provider is connected. Connect in Connections.")
    recency = selection["recency"]
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=DAYS[recency])) if recency in DAYS else None
    warnings = []
    for index, entry in enumerate(entries):
        provider = entry["provider"]
        path, body = adapter(provider, query, selection, cutoff)
        try:
            results = normalized_results(provider, gateway.json(entry, path, body, timeout=12), selection, cutoff)
        except ConnectorError as error:
            next_provider = entries[index + 1]["provider"] if index + 1 < len(entries) else None
            warnings.append(failure(provider, next_provider, error.status))
            continue
        if selection["safe_search"] and provider not in NATIVE_SAFE:
            warnings.append("This provider has no native Safe Search. Hearth applied a basic result filter.")
        return {"provider": provider, "results": results, "warnings": warnings,
                "latency_ms": round((time.monotonic() - start) * 1_000)}
    raise HearthError(" ".join(warnings) or "Web search failed. See Timeline for provider details.")
