import json
import re
from http.client import HTTPException
from urllib.parse import parse_qsl, unquote, urlsplit

from .connectors import ConnectorError
from .storage import HearthError

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
RESPONSE_LIMIT = 64 * 1024
CREDENTIAL_FIELDS = {
    "apikey", "authorization", "accesstoken", "refreshtoken", "spritetoken", "spritestoken", "token",
    "password", "secret", "clientsecret", "privatekey", "secretaccesskey", "connectionuri",
    "cardnumber", "cvc", "connecturl", "signedurl",
}
CREDENTIAL_TEXT = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{16,}|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{12,}"
    r"|pcsk_[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|hf_[A-Za-z0-9]{16,}|xox[bpars]-[A-Za-z0-9-]{10,}|sb_secret_[A-Za-z0-9_-]{10,}"
    r"|AIza[A-Za-z0-9_-]{30,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|bearer\s+[A-Za-z0-9._~+/-]{12,})"
    r"|https?://[A-Za-z0-9.-]+\.sprites\.app\b[^\s\"<>]*"
    r"|postgres(?:ql)?://[^\s\"<>]+"
)
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)
CREDENTIAL_ASSIGNMENT = re.compile(
    r"""(?ix) ( ["']? \b (?: api[\s_-]?key | access[\s_-]?token | refresh[\s_-]?token |
    sprites?[\s_-]?token | authorization | password | client[\s_-]?secret | private[\s_-]?key )
    ["']? \s* (?: : | = | \bis\b ) \s* )
    (?: "[^"\r\n]*" | '[^'\r\n]*' | (?: Bearer\s+ )? [^\s&,;}"']+ )"""
)
UPSTASH_READS = frozenset((
    "ping", "get", "mget", "exists", "ttl", "pttl", "type", "strlen", "getrange", "keys", "scan",
    "hget", "hgetall", "hmget", "hexists", "hkeys", "hlen", "hscan", "hstrlen", "hvals",
    "lindex", "llen", "lrange", "scard", "sdiff", "sinter", "sismember", "smembers", "smismember",
    "srandmember", "sscan", "sunion", "zcard", "zcount", "zlexcount", "zmscore", "zrange",
    "zrangebylex", "zrangebyscore", "zrank", "zrevrange", "zrevrangebylex", "zrevrangebyscore",
    "zrevrank", "zscan", "zscore",
))


def redact_text(text):
    text = PRIVATE_KEY.sub(lambda match: "[redacted]" + "\n" * match[0].count("\n"), text)
    return CREDENTIAL_TEXT.sub("[redacted]", CREDENTIAL_ASSIGNMENT.sub(r'\1"[redacted]"', text))


def credential_field(name):
    return re.sub(r"[^a-z0-9]", "", name.lower()) in CREDENTIAL_FIELDS


def scrub(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, dict):
        return {redact_text(key): "[redacted]" if credential_field(key) else scrub(item)
                for key, item in value.items()}
    return value


def contains_credential_field(value):
    if isinstance(value, list):
        return any(contains_credential_field(item) for item in value)
    if isinstance(value, dict):
        return any(credential_field(key) or contains_credential_field(item) for key, item in value.items())
    return False


def validate_request(provider, method, path, body):
    if not isinstance(method, str) or method.upper() not in METHODS:
        raise HearthError("Choose GET, POST, PUT, PATCH, DELETE, HEAD, or OPTIONS.")
    method = method.upper()
    if not isinstance(path, str) or not path or len(path) > 2_000 or not path.isascii() or any(
        ord(char) <= 32 or ord(char) == 127 for char in path
    ):
        raise HearthError("Use a URL-encoded provider-relative path.")
    parsed = urlsplit(path)
    route = unquote(parsed.path)
    # The gateway prefix must survive URL parsing and downstream decoding.
    if parsed.scheme or parsed.netloc or path.startswith("//") or "#" in path or "\\" in route or "%" in route or (
        ".." in route.split("/") or "." in route.split("/") or "//" in route or
        any(ord(char) < 32 or ord(char) == 127 for char in route)
    ):
        raise HearthError("Use a URL-encoded provider-relative path.")
    if any(key.lower() == "key" or credential_field(key) for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        raise HearthError("Fly supplies the credential. Remove it from the request.")
    if redact_text(unquote(path)) != unquote(path):
        raise HearthError("Remove private credentials and Sprite URLs from the request.")
    if body is not None:
        if method in ("GET", "HEAD"):
            raise HearthError("GET and HEAD requests take no JSON body.")
        if len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 16_000:
            raise HearthError("The request body is too large.")
        if contains_credential_field(body) or scrub(body) != body:
            raise HearthError("Remove private credentials and Sprite URLs from the request.")
    if provider == "upstash" and method == "GET" and route.strip("/").split("/")[0].lower() not in UPSTASH_READS:
        raise HearthError("Use an approved POST to run Redis commands that may change data.")
    return method, path.removeprefix("/")


def gateway_result(response):
    status = getattr(response, "status", 200)
    media_type = response.headers.get_content_type() if hasattr(response, "headers") else "application/json"
    raw = response.read(RESPONSE_LIMIT + 1)
    if len(raw) > RESPONSE_LIMIT:
        return {"status": status, "detail": "The response exceeded Hearth’s 64 KiB preview limit."}
    if not raw:
        return {"status": status, "data": None}
    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            result = scrub(json.loads(raw))
        except (UnicodeError, ValueError, RecursionError):
            return {"status": status, "detail": "The provider returned unreadable JSON."}
    elif media_type.startswith("text/") or media_type in ("application/xml", "application/xhtml+xml"):
        result = redact_text(raw.decode("utf-8", errors="replace"))
    else:
        return {"status": status, "content_type": media_type, "bytes": len(raw)}
    return {"status": status, "data": result}


def gateway_read(gateway, config, path):
    try:
        with gateway.open(config, path, method="GET") as response:
            return gateway_result(response)
    except (HTTPException, OSError):
        raise ConnectorError("The gateway response was interrupted.") from None
