import json
import re
from copy import deepcopy
from urllib.parse import quote

from .connectors import CORE_PROVIDERS, GATEWAY_SEGMENT, ConnectorError, valid_provider
from .storage import HearthError, ROOT, atomic_write, iso

CATALOG = {entry["slug"]: entry for entry in json.loads((ROOT / "config/catalog.json").read_text(encoding="utf-8"))}
DASHBOARD = "https://fly.io/dashboard/xuefeng-zhu/sprites/connectors"
ACCESS_RULE = "Name Prefix hearth"
SETTINGS = {"pinecone": "index", "agentmail": "inbox_id"}
INDEX = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,43}[a-z0-9])?")
INBOX = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
MODEL = re.compile(r"[A-Za-z0-9_.:/-]{1,150}")


def catalog_entry(provider):
    return CATALOG.get(provider) or {
        "slug": provider, "name": provider.replace("_", " ").replace("-", " ").title(),
        "category": "Other", "auth": None, "description": "Use this provider through the Sprites gateway.",
        "test_path": None, "docs_url": "https://docs.fly.io/sprites/concepts/connectors",
    }


def probe(gateway, config):
    provider = config["provider"]
    path = CATALOG[provider]["test_path"]
    if provider == "pinecone":
        path = f"indexes/{quote(config['index'], safe='')}"
    elif provider == "agentmail" and config["inbox_id"]:
        path = f"v0/inboxes/{quote(config['inbox_id'], safe='')}"
    try:
        with gateway.open(config, path, timeout=8) as response:
            raw = response.read(512 * 1024)
        try:
            result = json.loads(raw)
        except ValueError:
            result = None
        if isinstance(result, dict) and (result.get("error") or result.get("ok") is False):
            if result.get("error") in ("invalid_auth", "not_authed", "missing_scope", "token_revoked"):
                return "denied", "Test denied. Review the connector’s access rule and provider permissions."
            return "failed", "The provider reported an error. Review its configuration in Fly."
    except ConnectorError as error:
        if error.status in (401, 403):
            return "denied", "Test denied. Review the connector’s access rule and provider permissions."
        if error.status == 404 and provider in SETTINGS:
            return "failed", "The saved index or inbox could not be found. Check its name in the provider console."
        return "failed", "The gateway could not complete this check. Review the connection in Fly."
    except OSError:
        return "failed", "The test response was interrupted. Try again."
    return "passed", "The provider answered a read-only request."


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
        self.selected = {}
        self.found = set()
        self.available = set()
        self.checks = {}
        self.last_scan = None

    def load(self):
        config = deepcopy(self.defaults)
        config["gateway"] = {}
        if not self.path.is_file():
            return config
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HearthError("Hearth could not read the saved connector settings.") from None
        if not isinstance(data, dict):
            raise HearthError("Hearth could not read the saved connector settings.")

        # Preserve old IDs and model overrides while using the shipped fallback priority.
        models = data.get("llm")
        if isinstance(models, list):
            current = {item["provider"]: item for item in config["llm"]}
            for item in models:
                if isinstance(item, dict) and isinstance(item.get("provider"), str):
                    if model := current.get(item["provider"]):
                        self.merge(model, item)
        for provider in CORE_PROVIDERS[1:]:
            self.merge(config[provider], data.get(provider))
        saved_gateway = data.get("gateway")
        if isinstance(saved_gateway, dict):
            config["gateway"] = {
                provider: connection_id for provider, connection_id in saved_gateway.items()
                if valid_provider(provider) and isinstance(connection_id, str)
                and GATEWAY_SEGMENT.fullmatch(connection_id)
            }
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

    @staticmethod
    def configured_entries(config):
        return {**{item["provider"]: item for item in config["llm"] if item["provider"] != "mock"},
                **{provider: config[provider] for provider in CORE_PROVIDERS[1:]}}

    def gateway_entry(self, provider, connection_id):
        entry = {"provider": provider, "connection_id": connection_id}
        if gateway_provider := catalog_entry(provider).get("gateway_provider"):
            entry["gateway_provider"] = gateway_provider
        return entry

    def active_config(self):
        config = deepcopy(self.config)
        for provider, entry in self.configured_entries(config).items():
            entry["connection_id"] = self.selected.get(provider, "")
        config["gateway"] = {provider: self.gateway_entry(provider, connection_id)
                             for provider, connection_id in self.selected.items()}
        return config

    def report(self):
        providers = {}
        extra = self.found | self.available | self.config.get("gateway", {}).keys()
        for provider in (*CATALOG, *sorted(extra - CATALOG.keys())):
            info = catalog_entry(provider)
            if provider in self.selected:
                status, detail = "connected", "Fly grants this Sprite access."
            elif self.last_scan and (provider in self.found or provider in self.saved_ids(self.config)):
                status, detail = "unauthorized", "No authorization is visible for this Sprite. Review access in Fly."
            elif self.last_scan:
                status, detail = "not_set_up", "No connection is visible to this Sprite."
            else:
                status, detail = "unknown", "Discovery has not completed."
            test_status, test_detail = self.checks.get(provider, (None, None))
            field = SETTINGS.get(provider)
            providers[provider] = {
                **info, "status": status, "detail": detail, "test_status": test_status, "test_detail": test_detail,
                "settings": {field: self.config[provider][field]} if field else {},
                "can_test": provider in self.selected and bool(info["test_path"]),
                "dashboard_url": DASHBOARD, "access_rule": ACCESS_RULE, "pinned": provider in CORE_PROVIDERS,
            }
        return {"providers": providers, "last_scan": self.last_scan, "scan_error": self.scan_error}

    def saved_ids(self, config):
        return {**config.get("gateway", {}),
                **{provider: entry["connection_id"] for provider, entry in self.configured_entries(config).items()
                   if entry["connection_id"]}}

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
        saved = self.saved_ids(config)
        entries = self.configured_entries(config)
        selected = {}
        for provider, options in authorized.items():
            if not options:
                continue
            old = saved.get(provider)
            connection_id = old if old in options else min(options)
            selected[provider] = connection_id
            if provider in entries:
                entries[provider]["connection_id"] = connection_id
            else:
                config["gateway"][provider] = connection_id
        try:
            if config != previous:
                self.persist(config, "Before updating discovered Hearth connections")
        except HearthError as error:
            self.scan_error = str(error)
            return False
        self.checks = {provider: check for provider, check in self.checks.items()
                       if provider in selected and selected[provider] == self.selected.get(provider)}
        self.config, self.selected = config, selected
        self.found, self.available = found, set(authorized)
        self.last_scan = iso()
        self.scan_error = None
        return True

    def test(self, provider):
        if not isinstance(provider, str) or provider not in CATALOG or not CATALOG[provider]["test_path"]:
            raise HearthError("This connector has no read-only check in Hearth.")
        if provider not in self.selected:
            raise HearthError("Authorize this connector in Fly, then re-scan.")
        config = {**self.config.get(provider, {}), **self.gateway_entry(provider, self.selected[provider])}
        self.checks[provider] = probe(self.gateway, config)

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
        field = SETTINGS[provider]
        if config[provider][field] == value:
            return
        config[provider][field] = value
        self.persist(config, "Before saving Hearth connection settings")
        self.config = config
        self.checks.pop(provider, None)
