"""Check Hearth's private edge and public Page snapshots as an anonymous client."""

import os
import re
from http.client import HTTPException
from secrets import token_urlsafe
from urllib.error import HTTPError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from hearth.page_policy import TOKEN

REDIRECTS = {301, 302, 303, 307, 308}
ARTIFACT_PATH = "/api/artifacts/file"
PAGE_PATH = re.compile(r"/pages/[a-f0-9]{32}(?:/v/[1-9][0-9]{0,8})?")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def split_url(value):
    if any(char.isspace() or ord(char) < 32 or char == "\\" for char in value):
        raise ValueError
    return urlsplit(value)


def origin_key(parts):
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None:
        raise ValueError
    default_port = 443 if parts.scheme == "https" else 80
    port = parts.port
    return parts.scheme, parts.hostname, default_port if port is None else port


def parse_base(value):
    parts = split_url(value)
    origin_key(parts)
    if parts.path not in {"", "/"} or "?" in value or "#" in value:
        raise ValueError
    return parts._replace(path="").geturl()


def parse_private_path(value, *, artifact):
    parts = split_url(value)
    if not value.startswith("/") or value.startswith("//") or "#" in value:
        raise ValueError
    if artifact:
        ids = parse_qs(parts.query, keep_blank_values=True).get("id", [])
        if parts.path != ARTIFACT_PATH or len(ids) != 1 or not ids[0]:
            raise ValueError
    elif not PAGE_PATH.fullmatch(parts.path):
        raise ValueError
    return parts.geturl()


def parse_share(value):
    parts = split_url(value)
    origin_key(parts)
    if not parts.path.startswith("/p/") or "?" in value or "#" in value:
        raise ValueError
    token = parts.path.removeprefix("/p/")
    if not TOKEN.fullmatch(token):
        raise ValueError
    return parts._replace(path="").geturl(), token


def is_private_response(url, status, location):
    if status == 401:
        return True
    if status not in REDIRECTS or not location:
        return False
    try:
        split_url(location)
        target = urljoin(url, location)
        parts = split_url(target)
        origin_key(parts)
    except ValueError:
        return False
    return parts._replace(fragment="").geturl() != url


def read_env(name, parse):
    try:
        return parse(os.environ.get(name, ""))
    except ValueError:
        raise SystemExit(f"Missing or invalid {name}. See docs/testing.md.") from None


def probe(opener, method, url):
    # An empty JSON object cannot enqueue a chat if the private edge is misconfigured.
    request = Request(url, data=b"{}" if method == "POST" else None, method=method)
    if method == "POST":
        request.add_header("Content-Type", "application/json")
    try:
        response = opener.open(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers


def main():
    base = read_env("HEARTH_BASE_URL", parse_base)
    artifact = read_env("HEARTH_ARTIFACT_PATH", lambda path: parse_private_path(path, artifact=True))
    page = read_env("HEARTH_PAGE_PATH", lambda path: parse_private_path(path, artifact=False))
    public, active = read_env("HEARTH_PAGE_SHARE_URL", parse_share)
    revoked_origin, revoked = read_env("HEARTH_REVOKED_PAGE_SHARE_URL", parse_share)
    if origin_key(urlsplit(public)) == origin_key(urlsplit(base)):
        raise SystemExit("Use the separate public Pages origin for the share URLs.")
    if origin_key(urlsplit(revoked_origin)) != origin_key(urlsplit(public)) or active == revoked:
        raise SystemExit("Use two different tokens from the same public Pages origin.")

    opener = build_opener(ProxyHandler({}), NoRedirect())
    failures = []

    def check(method, label, url, expected):
        try:
            status, headers = probe(opener, method, url)
        except (HTTPException, OSError, ValueError):
            failures.append(f"{method} {label} could not connect or read a response.")
            return
        if expected is None:
            passed = is_private_response(url, status, headers.get("Location"))
        else:
            passed = status == expected
            if expected == 200:
                passed = passed and headers.get_content_type() == "text/html"
        if passed:
            print(f"PASS {method} {label} ({status})")
        else:
            want = expected if expected != 200 else "200 with HTML"
            failures.append(f"{method} {label} returned {status}, expected {want or 'an HTTP redirect or 401'}.")

    workspace_routes = {
        "health": "/health", "state": "/api/state", "chat": "/api/chat",
        "artifact": artifact, "private Page": page,
    }
    for label, path in {**workspace_routes, "share token on workspace origin": "/p/" + active}.items():
        for method in ("GET", "POST"):
            check(method, label, base + path, None)

    for method in ("GET", "HEAD"):
        check(method, "active Page share", public + "/p/" + active, 200)
    for label, suffix in {
        "missing Page token": "",
        "malformed Page token": "invalid",
        "unknown Page token": token_urlsafe(32),
        "revoked Page share": revoked,
    }.items():
        check("GET", label, public + "/p/" + suffix, 404)
    for path in ("/health", "/api/state", "/api/chat", ARTIFACT_PATH, "/pages/"):
        check("GET", f"{path} on public Pages origin", public + path, 404)

    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
