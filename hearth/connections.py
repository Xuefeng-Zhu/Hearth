import json
import re
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from urllib.parse import quote

from .connectors import DISCOVERY_PROVIDERS, GATEWAY_SEGMENT, MODEL_PATHS, PINECONE_HEADERS, ConnectorError
from .storage import HearthError, atomic_write, iso

SETTINGS = {"pinecone": "index", "agentmail": "inbox_id"}
INDEX = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,43}[a-z0-9])?")
INBOX = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
MODEL = re.compile(r"[A-Za-z0-9_.:/-]{1,150}")
PROBE_TIMEOUT = 8


def provider_config(config, provider):
    if provider == "meta":
        return next(item for item in config["llm"] if item["provider"] == "meta")
    return config[provider]


def probe(gateway, config):
    provider = config["provider"]
    options = {"timeout": PROBE_TIMEOUT}
    try:
        if provider == "meta":
            result = gateway.json(config, MODEL_PATHS["meta"], {
                "model": config["model"], "messages": [{"role": "user", "content": "Reply OK."}],
                "max_completion_tokens": 16, "reasoning_effort": "minimal", "store": False,
            }, **options)
            success = bool(result.get("choices"))
            detail = "Muse Spark accepted a short completion request."
        elif provider == "pinecone":
            index = config["index"]
            result = gateway.json(config, f"indexes/{quote(index, safe='')}", headers=PINECONE_HEADERS, **options)
            success = result.get("name") == index
            detail = "Pinecone returned the configured index."
        elif provider == "tavily":
            result = gateway.json(config, "search", {
                "query": "Fly.io", "search_depth": "basic", "max_results": 1, "auto_parameters": False,
            }, **options)
            success = isinstance(result.get("results"), list)
            detail = "Tavily answered a one-result search."
        elif config["inbox_id"]:
            inbox = quote(config["inbox_id"], safe="")
            result = gateway.json(config, f"v0/inboxes/{inbox}", **options)
            success = bool(result.get("inbox_id"))
            detail = "AgentMail returned the configured inbox."
        else:
            result = gateway.json(config, "v0/inboxes?limit=1", **options)
            success = isinstance(result.get("inboxes"), list)
            detail = "AgentMail is reachable. Save an inbox ID to enable sending."
    except ConnectorError as error:
        if error.status in (401, 403):
            return "unauthorized", "Access was denied. Check the connector’s access rule and provider permissions."
        if error.status == 404 and provider in SETTINGS:
            return "unavailable", "The gateway could not find the saved index or inbox. Check its name in the provider console."
        return "unavailable", "The gateway could not complete this check. Check the connection in Fly and try again."
    if not success or result.get("error"):
        return "unavailable", "The connector returned an unexpected response. Check its configuration in Fly."
    return "connected", detail


class Connections:
    def __init__(self, defaults, path, gateway, storage, checkpoints):
        self.defaults = defaults
        self.path = path
        self.gateway = gateway
        self.storage = storage
        self.checkpoints = checkpoints
        self.reset()

    def reset(self):
        try:
            self.config = self.load()
        except HearthError as error:
            self.config = deepcopy(self.defaults)
            self.scan_error = str(error)
        else:
            self.scan_error = None
        self.results = {}
        self.testable = set()
        self.last_scan = None

    def load(self):
        if not self.path.is_file():
            return deepcopy(self.defaults)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HearthError("Hearth could not read the saved connector settings.") from None
        if not isinstance(data, dict):
            raise HearthError("Hearth could not read the saved connector settings.")

        # Copy only known settings from older overrides. Gateway metadata and request bodies
        # never become part of the saved document.
        config = deepcopy(self.defaults)
        models = data.get("llm")
        if isinstance(models, list):
            current = {item["provider"]: item for item in config["llm"]}
            ordered = []
            for item in models:
                if not isinstance(item, dict) or not isinstance(item.get("provider"), str):
                    continue
                if model := current.pop(item["provider"], None):
                    self.merge(model, item)
                    ordered.append(model)
            config["llm"] = ordered + list(current.values())
        for provider in DISCOVERY_PROVIDERS[1:]:
            self.merge(config[provider], data.get(provider))
        return config

    @staticmethod
    def merge(config, saved):
        if not isinstance(saved, dict):
            return
        rules = {"connection_id": GATEWAY_SEGMENT, "model": MODEL, "index": INDEX,
                 "inbox_id": INBOX, "namespace": GATEWAY_SEGMENT}
        for key in config.keys() & rules.keys():
            value = saved.get(key)
            if isinstance(value, str) and (rules[key].fullmatch(value) or
                                          (not value and key in ("connection_id", "inbox_id"))):
                config[key] = value

    def active_config(self):
        config = deepcopy(self.config)
        for provider in DISCOVERY_PROVIDERS:
            if self.results.get(provider, (None,))[0] != "connected":
                provider_config(config, provider)["connection_id"] = ""
        # A previously saved order may have placed the mock ahead of a newly linked model.
        config["llm"].sort(key=lambda item: item["provider"] == "mock")
        return config

    def report(self):
        providers = {}
        for provider in DISCOVERY_PROVIDERS:
            config = provider_config(self.config, provider)
            status, detail = self.results.get(provider, ("unknown", "Hearth has not checked this connection yet."))
            field = SETTINGS.get(provider)
            providers[provider] = {
                "status": status, "detail": detail, "settings": {field: config[field]} if field else {},
                "can_test": provider in self.testable,
            }
        return {"providers": providers, "last_scan": self.last_scan, "scan_error": self.scan_error}

    def persist(self, config, comment):
        with self.storage.lock():
            try:
                self.checkpoints.create(comment)
                atomic_write(self.path, json.dumps(config, indent=2) + "\n")
            except (HearthError, OSError):
                raise HearthError("Hearth could not checkpoint and save connector settings.") from None

    def scan(self):
        try:
            previous = self.load()
        except HearthError as error:
            self.scan_error = str(error)
            return False
        try:
            authorized, found = self.gateway.discover()
        except ConnectorError:
            self.scan_error = "Hearth could not reach Sprites discovery. Try again from the Sprite."
            return False
        config = deepcopy(previous)
        results = {}
        candidates = {}
        for provider in DISCOVERY_PROVIDERS:
            entry = provider_config(config, provider)
            options = authorized[provider]
            if options:
                # Keep an existing choice when possible. Use a stable choice on first discovery.
                if entry["connection_id"] not in options:
                    entry["connection_id"] = min(options)
                candidates[provider] = entry
            elif provider in found or entry["connection_id"]:
                results[provider] = (
                    "unauthorized", "The gateway lists no authorized connection for this Sprite. Check the connector in Fly.",
                )
            else:
                results[provider] = ("not_set_up", "No connector is visible to this Sprite.")
        if candidates:
            with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
                checks = pool.map(lambda entry: probe(self.gateway, entry), candidates.values())
                results.update(zip(candidates, checks))
        try:
            if config != previous:
                self.persist(config, "Before updating discovered Hearth connections")
        except HearthError as error:
            self.scan_error = str(error)
            return False
        self.config, self.results = config, results
        self.testable = set(candidates)
        self.last_scan = iso()
        self.scan_error = None
        return True

    def test(self, provider):
        if provider not in DISCOVERY_PROVIDERS:
            raise HearthError("Unknown connector.")
        entry = provider_config(self.config, provider)
        if provider not in self.testable:
            raise HearthError("Authorize this connector in Fly, then re-scan.")
        self.results[provider] = probe(self.gateway, entry)

    def save(self, provider, value):
        if not isinstance(provider, str) or provider not in SETTINGS or not isinstance(value, str):
            raise HearthError("Invalid connector settings.")
        value = value.strip()
        if provider == "pinecone" and not INDEX.fullmatch(value):
            raise HearthError("Use a Pinecone index name of 1–45 lowercase letters, digits, or hyphens.")
        if provider == "agentmail" and value and (len(value) > 254 or not INBOX.fullmatch(value)):
            raise HearthError("Use the AgentMail inbox address, or leave it blank to disable sending.")
        config = self.load()
        if config != self.config:
            raise HearthError("Saved connection settings changed. Re-scan and try again.")
        entry = provider_config(config, provider)
        field = SETTINGS[provider]
        if entry[field] == value:
            return
        entry[field] = value
        self.persist(config, "Before saving Hearth connection settings")
        self.config = config
        if provider in self.testable:
            self.test(provider)
