"""Browserbase operations through the Fly Sprites connector."""

import asyncio
import hashlib
import io
import ipaddress
import re
import time
from functools import lru_cache
from urllib.parse import parse_qsl, unquote, urlsplit

from .connectors import GATEWAY, GATEWAY_SEGMENT, ConnectorError
from .gateway_tools import credential_field, redact_text
from .storage import HearthError, new_id

PROVIDER = "browserbase"
TEST_PATH = "v1/sessions?status=RUNNING"
NOT_CONNECTED = "Browserbase isn’t connected. Add Browserbase in Fly Sprites and grant the Hearth Sprite access."
DENIED = "Fly denied Browserbase access. Check the Hearth Sprite’s access in Fly."
DISABLED = "Web browsing is off. Turn on Allow web browsing in Settings → Search."
SESSION_SECONDS = 90
TEXT_LIMIT = 16_000
TOOL_NAMES = frozenset({"browse_fetch", "browse_search", "browse_session"})
STEP_TYPES = ("navigate", "scroll", "wait_for", "click", "fill")
WRITE_STEPS = {"click", "fill"}
SCREENSHOT_ID = re.compile(r"[0-9a-f]{32}\.png")
GATEWAY_HOST = urlsplit(GATEWAY).hostname


def settings(value):
    if not isinstance(value, dict) or value.keys() - {"allowed"} or (
        "allowed" in value and type(value["allowed"]) is not bool
    ):
        raise HearthError("Invalid web browsing settings.")
    return {"allowed": value.get("allowed", True)}


def error_message(error):
    if error.status == 404:
        return NOT_CONNECTED
    if error.status in (401, 403):
        return DENIED
    if error.status == 429:
        return "Browserbase is rate limited. Try again shortly."
    if error.status == 504:
        return "The Browserbase gateway request timed out."
    suffix = f" (HTTP {error.status})" if error.status else ""
    return f"The Browserbase gateway could not complete this request{suffix}."


def text(value, limit):
    if not isinstance(value, str):
        return ""
    return redact_text(value.strip())[:limit]


def page_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value
    ) or "\\" in value:
        raise HearthError("Use a public HTTP or HTTPS page URL.")
    try:
        url = urlsplit(value)
        host, port = url.hostname, url.port
    except ValueError:
        raise HearthError("Use a public HTTP or HTTPS page URL.") from None
    if url.scheme not in ("http", "https") or not host or url.username or url.password or "@" in url.netloc:
        raise HearthError("Use a public HTTP or HTTPS page URL.")
    if port not in (None, 80, 443):
        raise HearthError("Use a public page on the standard HTTP or HTTPS port.")
    host = host.rstrip(".")
    try:
        public = ipaddress.ip_address(host).is_global
    except ValueError:
        public = ("." in host and not host.endswith((".local", ".localhost", ".internal", ".test", ".onion"))
                  and bool(re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host, re.I))
                  and not re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host, re.I))
    if not public or any(credential_field(key) or key.lower() == "key"
                         for key, _ in parse_qsl(url.query, keep_blank_values=True)):
        raise HearthError("Use a public page URL without credentials.")
    decoded = unquote(value)
    if redact_text(decoded) != decoded:
        raise HearthError("Use a public page URL without credentials.")
    return value


def origin(value):
    url = urlsplit(value)
    return url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80)


def normalize_steps(value):
    if not isinstance(value, list) or len(value) > 8:
        raise HearthError("Provide up to eight browser steps.")
    result = []
    for step in value:
        if not isinstance(step, dict) or step.keys() - {"action", "target", "text"}:
            raise HearthError("Use structured browser steps with an action and optional target or text.")
        action = step.get("action")
        if action not in STEP_TYPES:
            raise HearthError("Use navigate, scroll, wait_for, click, or fill for browser steps.")
        target = step.get("target", "down" if action == "scroll" else "")
        if not isinstance(target, str) or not target.strip() or len(target) > 2048 or redact_text(target) != target:
            raise HearthError("Use a valid browser step target without credentials.")
        target = target.strip()
        if action == "navigate":
            target = page_url(target)
        elif action == "scroll" and target not in ("up", "down"):
            raise HearthError("Scroll direction must be up or down.")
        item = {"action": action, "target": target}
        if action == "fill":
            content = step.get("text")
            if not isinstance(content, str) or len(content) > 1000 or redact_text(content) != content:
                raise HearthError("Fill steps need text without credentials.")
            item["text"] = content
        elif "text" in step:
            raise HearthError("Only fill steps take browser input text.")
        result.append(item)
    return result


def service_url(value, scheme, *, cdp=False):
    try:
        if not isinstance(value, str) or any(char.isspace() for char in value) or "\\" in value:
            return None
        url = urlsplit(value)
        if url.scheme != scheme or url.username or url.password or url.port not in (None, 443):
            return None
        host = url.hostname or ""
        if cdp:
            # Fly documents a signed session URL. Never forward a legacy key-bearing URL.
            if any(re.sub(r"[^a-z0-9]", "", key.lower()) in {"apikey", "xbbapikey", "key"}
                   for key, _ in parse_qsl(url.query)):
                return None
            if host == GATEWAY_HOST and url.path.startswith("/v1/gateway/browserbase/"):
                return value
            if host.startswith("connect.") and host.endswith(".browserbase.com"):
                return value
        elif (host in ("browserbase.com", "browserbase.live") or
              host.endswith((".browserbase.com", ".browserbase.live"))):
            return value
    except ValueError:
        pass
    return None


def live_view(data):
    candidates = [data]
    if isinstance(data.get("pages"), list):
        candidates.extend(page for page in reversed(data["pages"]) if isinstance(page, dict))
    return next((url for item in candidates for field in ("debuggerFullscreenUrl", "debuggerUrl")
                 if (url := service_url(item.get(field), "https"))), None)


def screenshot_path(storage, name):
    if not isinstance(name, str) or not SCREENSHOT_ID.fullmatch(name):
        raise HearthError("Browser screenshot not found.")
    return storage.live / "browse" / name


@lru_cache(maxsize=8)
def demo_image(domain="fly.io"):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (960, 520), "#f5f0e6")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 960, 56), fill="#252c26")
    draw.text((37, 16), "Hearth  /  Browserbase demo", font=ImageFont.load_default(size=20), fill="#fff9ed")
    draw.text((64, 117), "Hacksgiving" if domain == "fly.io" else domain[:25],
              font=ImageFont.load_default(size=74 if domain == "fly.io" else 50), fill="#252c26")
    draw.text((67, 225), "Fly.io community event" if domain == "fly.io" else "Browser session",
              font=ImageFont.load_default(size=32), fill="#3a493c")
    draw.line((68, 294, 891, 294), fill="#b2a794", width=2)
    draw.text((68, 338), "Sample page for the browsing demo", font=ImageFont.load_default(size=24), fill="#3a493c")
    draw.text((68, 389), "fly.io/hacksgiving/" if domain == "fly.io" else domain[:60],
              font=ImageFont.load_default(size=22), fill="#3a493c")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class CdpUnavailable(HearthError):
    pass


class Browserbase:
    def __init__(self, gateway):
        self.gateway = gateway

    def call(self, path, body=None, *, timeout=15, allow_array=False):
        try:
            response = self.gateway.request(f"{PROVIDER}/{path}", body, None, timeout)
            return self.gateway.read_json(response, allow_array=allow_array)
        except ConnectorError as error:
            raise HearthError(error_message(error)) from None

    def running_sessions(self, *, timeout=8):
        response = self.gateway.request(f"{PROVIDER}/{TEST_PATH}", None, None, timeout)
        sessions = self.gateway.read_json(response, allow_array=True)
        if not isinstance(sessions, list):
            raise ConnectorError("Browserbase did not return its running sessions list.")

    def test(self):
        try:
            self.running_sessions()
        except ConnectorError as error:
            raise HearthError(error_message(error)) from None

    def fetch(self, url, *, mock=False):
        url = page_url(url)
        if mock:
            return {"url": url, "status": 200, "markdown": self.demo_text(url), "mock": True}
        data = self.call("v1/fetch", {"url": url, "format": "markdown", "allowRedirects": True})
        status = data.get("statusCode")
        if type(status) is not int or not 200 <= status < 300:
            raise HearthError(f"The page returned HTTP {status}." if type(status) is int
                              else "Browserbase did not return a page status.")
        if not isinstance(data.get("content"), str):
            raise HearthError("Browserbase did not return page text.")
        return {"url": url, "status": status, "markdown": text(data["content"], TEXT_LIMIT)}

    def search(self, query, *, mock=False):
        query = text(query, 200)
        if not query:
            raise HearthError("Enter a web search query.")
        if mock:
            return {"query": query, "mock": True, "results": [{"title": "Hacksgiving",
                    "url": "https://fly.io/hacksgiving/", "snippet": "Sample Fly.io community event page."}]}
        data = self.call("v1/search", {"query": query, "numResults": 5, "excerpts": True})
        if not isinstance(data.get("results"), list):
            raise HearthError("Browserbase did not return search results.")
        results = []
        for item in data["results"][:5]:
            if not isinstance(item, dict):
                continue
            try:
                url = page_url(item.get("url"))
            except HearthError:
                continue
            excerpts = item.get("excerpts")
            snippet = " ".join(text(value, 800) for value in excerpts[:3]) if isinstance(excerpts, list) else ""
            results.append({"title": text(item.get("title"), 240), "url": url, "snippet": snippet[:1000]})
        return {"query": query, "results": results}

    @staticmethod
    def demo_text(url):
        if urlsplit(url).hostname == "fly.io" and urlsplit(url).path.rstrip("/") == "/hacksgiving":
            return "Git together to build something fun. Bring a project or join a team at Fly.io’s sample Hacksgiving event."
        return f"This is a simulated read of {urlsplit(url).hostname}. The sample shows a successful page visit."

    def session(self, url, steps, event, *, mock=False, approved=False):
        if not approved and any(step["action"] in WRITE_STEPS for step in steps):
            raise HearthError("Ask the user to approve the browser actions first.")
        started = time.monotonic()
        session_id = None
        detail = None
        failure = None
        result = {}
        screenshot = None
        active = {"id": new_id(), "domain": urlsplit(url).hostname}
        event("browse_active", active)
        try:
            if mock:
                session_id = "demo-" + hashlib.sha256(url.encode()).hexdigest()[:12]
                event("browse_active", {**active, "mock": True})
                time.sleep(2.2)
                final_url = next((step["target"] for step in reversed(steps) if step["action"] == "navigate"), url)
                result = {"url": final_url, "text": self.demo_text(final_url), "mock": True}
                screenshot = demo_image(urlsplit(final_url).hostname)
            else:
                try:
                    info = self.call("v1/sessions", {"timeout": SESSION_SECONDS}, timeout=10)
                    session_id = info.get("id")
                    if not isinstance(session_id, str) or not GATEWAY_SEGMENT.fullmatch(session_id):
                        session_id = None
                        raise HearthError("Browserbase did not return a session ID.")
                    endpoint = service_url(info.get("connectUrl"), "wss", cdp=True)
                    if not endpoint:
                        raise CdpUnavailable()
                    deadline = started + SESSION_SECONDS - 6

                    def ready(debug_url):
                        event("browse_active", {**active, "live_url": debug_url})

                    debug = live_view(info)
                    if debug:
                        ready(debug)
                    result, screenshot = asyncio.run(self.drive(endpoint, url, steps, debug, session_id, deadline,
                                                                 ready, approved=approved))
                finally:
                    if session_id:
                        try:
                            self.call(f"v1/sessions/{session_id}", {"status": "REQUEST_RELEASE"}, timeout=5)
                        except HearthError:
                            detail = "Browserbase did not confirm release. The session expires automatically within 90 seconds."
        except CdpUnavailable:
            fallback = "Browserbase’s CDP connection couldn’t be opened from the Sprite. Used Fetch for the starting page."
            if approved:
                fallback += " The approved steps did not run."
            try:
                result = self.fetch(url)
                result["fallback"] = fallback
            except HearthError as error:
                failure = f"Browserbase’s CDP connection couldn’t be opened from the Sprite. Fetch also failed. {error}"
        except (HearthError, TimeoutError) as error:
            failure = str(error) or "The browser session timed out."
        finally:
            event("browse_finished", {"id": active["id"]})
        if detail:
            result["warning"] = detail
        if failure:
            result["error"] = failure
        return {**result, "session_id": session_id}, screenshot

    async def drive(self, endpoint, url, steps, debug, session_id, deadline, ready, *, approved):
        try:
            from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, async_playwright
        except ImportError:
            raise CdpUnavailable() from None

        try:
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                async with async_playwright() as playwright:
                    try:
                        browser = await playwright.chromium.connect_over_cdp(endpoint, timeout=8000)
                    except PlaywrightError:
                        raise CdpUnavailable() from None
                    context = await browser.new_context(service_workers="block", accept_downloads=False)
                    context.set_default_timeout(8_000)
                    context.set_default_navigation_timeout(18_000)

                    async def restrict(route):
                        request = route.request
                        try:
                            page_url(request.url)
                        except HearthError:
                            await route.abort()
                            return
                        if request.method not in ("GET", "HEAD", "OPTIONS") and (
                            not approved or origin(request.url) != origin(url)
                        ):
                            await route.abort()
                        else:
                            await route.continue_()

                    await context.route("**/*", restrict)
                    if not approved:
                        await context.route_web_socket("**/*", lambda socket: socket.close())
                    page = await context.new_page()
                    if not debug:
                        try:
                            data = await asyncio.to_thread(self.call, f"v1/sessions/{session_id}/debug", timeout=3)
                            debug = live_view({"pages": data.get("pages")} if data.get("pages") else data)
                        except HearthError:
                            pass
                        if debug:
                            ready(debug)
                    response = await page.goto(url, wait_until="domcontentloaded")
                    if response and response.status >= 400:
                        raise HearthError(f"The page returned HTTP {response.status}.")
                    for step in steps:
                        action, target = step["action"], step["target"]
                        if action == "navigate":
                            await page.goto(target, wait_until="domcontentloaded")
                        elif action == "scroll":
                            await page.mouse.wheel(0, 620 if target == "down" else -620)
                        elif action == "wait_for":
                            await page.locator(target).first.wait_for()
                        elif approved and origin(page.url) == origin(url):
                            if action == "fill":
                                field = page.locator(target).first
                                input_type = (await field.get_attribute("type") or "").lower()
                                autocomplete = (await field.get_attribute("autocomplete") or "").lower()
                                if input_type == "password" or re.search(r"password|one-time-code|\bcc-", autocomplete):
                                    raise HearthError("Enter credentials yourself in your own browser.")
                                await field.fill(step["text"])
                            else:
                                existing_pages = set(context.pages)
                                await page.locator(target).first.click()
                                page = next((item for item in reversed(context.pages) if item not in existing_pages), page)
                        else:
                            raise HearthError("Approval is needed for this action on the current page.")
                    final_url = page_url(page.url)
                    try:
                        await page.wait_for_load_state("load", timeout=4_000)
                    except PlaywrightTimeout:
                        pass
                    image = await page.screenshot(type="png", animations="disabled")
                    body = page.locator("body")
                    content = text(await body.inner_text(), TEXT_LIMIT) if await body.count() else ""
                    return {"url": final_url, "text": content}, image
        except PlaywrightError:
            raise HearthError("The browser could not finish the page or its requested steps.") from None
        except TimeoutError:
            raise HearthError("The browser session reached its time limit.") from None
