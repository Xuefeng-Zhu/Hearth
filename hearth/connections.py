import json
import re
from copy import deepcopy
from urllib.parse import quote

from .connectors import CORE_PROVIDERS, GATEWAY_SEGMENT, MODELS_PATHS, MODEL_PATHS, ConnectorError, valid_provider
from .gateway_tools import redact_text
from .storage import HearthError, ROOT, atomic_write, iso
from . import box, pinecone, recall, router, search

CATALOG = {entry["slug"]: entry for entry in json.loads((ROOT / "config/catalog.json").read_text(encoding="utf-8"))}
DASHBOARD = "https://fly.io/dashboard/xuefeng-zhu/sprites/connectors"
ACCESS_RULE = "Name Prefix hearth"
SETTINGS = {"pinecone": "index", "agentmail": "inbox_id"}
INDEX = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,43}[a-z0-9])?")
INBOX = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
MODEL = re.compile(r"[A-Za-z0-9_.:/-]{1,150}")
NON_CHAT_MODEL = re.compile(r"(?:^|[/_.:-])(?:embeddings?|rerank(?:er)?|whisper|tts|stt|dall-e|"
                            r"image|transcribe|moderation|guard|safeguard)(?:$|[/_.:-])", re.I)


def valid_model(value):
    return isinstance(value, str) and bool(MODEL.fullmatch(value)) and redact_text(value) == value


def validate_pool(rows):
    if not isinstance(rows, list) or len(rows) > router.MAX_POOL:
        raise HearthError(f"Supply a routing pool of up to {router.MAX_POOL} models.")
    pool = {}
    for row in rows:
        if not isinstance(row, dict) or row.keys() - {"provider", "model", "tags"}:
            raise HearthError("Invalid routing pool model.")
        provider, model = row.get("provider"), row.get("model")
        if not isinstance(provider, str) or provider not in MODEL_PATHS or not valid_model(model):
            raise HearthError("Choose a valid routing pool provider and model.")
        key = (provider, model)
        if key in pool:
            raise HearthError("Each model can appear only once in the routing pool.")
        pool[key] = {"provider": provider, "model": model, "tags": router.validate_tags(row.get("tags", {}))}
    return list(pool.values())


def chat_models(provider, data):
    if provider == "gemini":
        entries, key = data.get("models"), "name"
    elif provider == "ollama":
        entries, key = data.get("models"), "model"
    else:
        entries, key = data.get("data"), "id"
    if not isinstance(entries, list):
        raise ConnectorError("The provider did not return a model list.")
    models = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model = entry.get(key) or (entry.get("name") if provider == "ollama" else None)
        if not valid_model(model) or NON_CHAT_MODEL.search(model):
            continue
        if provider == "gemini" and "generateContent" not in (entry.get("supportedGenerationMethods") or []):
            continue
        task = entry.get("pipeline_tag")
        if task and task not in ("conversational", "text-generation", "image-text-to-text", "text2text-generation"):
            continue
        architecture = entry.get("architecture")
        if isinstance(architecture, dict) and any(
            modalities is not None and (not isinstance(modalities, list) or "text" not in modalities)
            for modalities in (architecture.get("input_modalities"), architecture.get("output_modalities"))
        ):
            continue
        if provider == "huggingface" and ":" not in model:
            model += ":fastest"
        models.add(model.removeprefix("models/") if provider == "gemini" else model)
    return sorted(models, key=str.casefold)


def list_chat_models(gateway, entry):
    provider = entry["provider"]
    if provider not in MODELS_PATHS:
        return []
    return chat_models(provider, gateway.json(entry, MODELS_PATHS[provider], timeout=8))


def with_model(gateway, entry):
    if entry["model"]:
        return entry
    models = list_chat_models(gateway, entry)
    if not models:
        raise ConnectorError("Choose a model ID in Settings.")
    return {**entry, "model": models[0]}


def catalog_entry(provider):
    return CATALOG.get(provider) or {
        "slug": provider, "name": provider.replace("_", " ").replace("-", " ").title(),
        "category": "Other", "auth": None, "description": "Use this provider through the Sprites gateway.",
        "test_path": None, "docs_url": "https://docs.fly.io/sprites/concepts/connectors",
    }


def connector_uses(provider):
    if provider == "box":
        return ["Artifacts", "Tools"]
    if provider == "vocalbridge":
        return ["Voice call"]
    uses = []
    if provider in MODEL_PATHS:
        uses.append("Brain")
    if provider in search.PROVIDERS:
        uses.append("Search")
    if provider in recall.BACKENDS and provider != "keyword":
        uses.append("Memory")
    if provider == "huggingface":
        uses.append("Voice")
    return [*uses, "Tools"]


def probe(gateway, config):
    provider = config["provider"]
    path = CATALOG[provider]["test_path"]
    if provider == "pinecone":
        path = "indexes"
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
        self.check_times = {}
        self.last_scan = None

    def load(self):
        config = deepcopy(self.defaults)
        config["gateway"] = {}
        config.setdefault("brain", {"provider": "auto", "model": ""})
        config.setdefault("brain_pool", [])
        config["memory"] = recall.settings(config.get("memory", {}))
        config["search"] = search.settings(config.get("search", {}))
        config["artifacts"] = box.settings(config.get("artifacts", {}))
        config["box_folders"] = {}
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
        vector = data.get("pinecone")
        if isinstance(vector, dict):
            entry = config["pinecone"]
            namespace = vector.get("namespace")
            if isinstance(namespace, str) and pinecone.NAMESPACE.fullmatch(namespace):
                # Earlier releases used hearth as a prefix for workspace hashes.
                entry["namespace"] = "frank" if namespace == "hearth" and not vector.get("host") else namespace
            host = vector.get("host")
            if isinstance(host, str) and pinecone.INDEX_HOST.fullmatch(host):
                entry["host"] = host
            for field in ("cloud", "region", "embedding_model"):
                if valid_model(value := vector.get(field)):
                    entry[field] = value
        saved_gateway = data.get("gateway")
        if isinstance(saved_gateway, dict):
            config["gateway"] = {
                provider: connection_id for provider, connection_id in saved_gateway.items()
                if valid_provider(provider) and isinstance(connection_id, str)
                and GATEWAY_SEGMENT.fullmatch(connection_id)
            }
        brain = data.get("brain")
        if isinstance(brain, dict):
            provider, model = brain.get("provider"), brain.get("model")
            if isinstance(provider, str) and provider in MODEL_PATHS and valid_model(model):
                config["brain"] = {"provider": provider, "model": model}
            elif provider in ("auto", "priority", "smart", "mock"):
                config["brain"] = {"provider": provider, "model": ""}
        if "brain_pool" in data:
            try:
                config["brain_pool"] = validate_pool(data["brain_pool"])
            except HearthError:
                pass
        for key, validate in (("memory", recall.settings), ("search", search.settings), ("artifacts", box.settings)):
            if key in data:
                try:
                    config[key] = validate(data[key])
                except HearthError:
                    pass
        folders = data.get("box_folders")
        if (isinstance(folders, dict) and folders.get("name") == config["artifacts"]["folder_name"]
                and folders.get("connection") == config["gateway"].get("box")
                and box.box_id(folders.get("root")) and isinstance(folders.get("kinds"), dict)
                and set(folders["kinds"]) == box.FOLDERS.keys() and all(map(box.box_id, folders["kinds"].values()))):
            config["box_folders"] = folders
        return config

    def save_preferences(self, key, selection):
        config = self.load()
        if config != self.config:
            raise HearthError("Saved connection settings changed. Re-scan and try again.")
        if selection != config[key]:
            if key == "artifacts" and selection["folder_name"] != config[key]["folder_name"]:
                config["box_folders"] = {}
            config[key] = selection
            self.persist(config, f"Before saving Hearth {key} settings")
            self.config = config

    def save_box_folders(self, folders):
        with self.storage.lock():
            config = self.load()
            config["box_folders"] = folders
            atomic_write(self.path, json.dumps(config, indent=2) + "\n")
            self.config = config

    def save_pinecone_index(self, entry, info):
        with self.storage.lock():
            config = self.load()
            current = config["pinecone"]
            if (entry["connection_id"] != self.selected.get("pinecone") or
                    any(current[key] != entry[key] for key in ("index", "namespace"))):
                return
            updated = {"host": info["host"], "namespace": entry["namespace"],
                       "embedding_model": info["embedding_model"]}
            if any(current.get(key) != value for key, value in updated.items()):
                current.update(updated)
                atomic_write(self.path, json.dumps(config, indent=2) + "\n")
                self.config = config

    @staticmethod
    def merge(config, saved):
        if not isinstance(saved, dict):
            return
        if "model" in config and valid_model(saved.get("model")):
            config["model"] = saved["model"]
        rules = {"connection_id": GATEWAY_SEGMENT, "index": INDEX,
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

    def brain_info(self):
        saved = self.config.get("brain", {"provider": "auto", "model": ""})
        entries = self.configured_entries(self.config)
        providers = []
        for provider in CATALOG:
            if CATALOG[provider]["category"] != "AI models" or (
                provider not in self.selected and provider != saved["provider"]
            ):
                continue
            providers.append({
                "provider": provider, "name": CATALOG[provider]["name"],
                "default_model": entries.get(provider, {}).get("model", ""),
                "available": provider in self.selected, "supported": provider in MODEL_PATHS,
            })
        defaults = self.config.get("brain_tags", {})
        pool = self.config.get("brain_pool", [])
        default_pool = [{"provider": provider, "model": entry["model"]}
                        for provider, entry in entries.items() if provider in MODEL_PATHS
                        and provider in self.selected and entry["model"]]

        def describe(rows):
            return [{**row, "tags": router.model_tags(row, defaults)} for row in rows]

        return {"selection": saved, "providers": providers, "pool": describe(pool),
                "default_pool": describe(default_pool)}

    def brain_selection(self, provider, model=""):
        if not isinstance(provider, str) or not isinstance(model, str):
            raise HearthError("Choose a valid brain provider and model.")
        if provider in ("auto", "priority", "smart", "mock"):
            return {"provider": provider, "model": ""}
        if provider not in MODEL_PATHS:
            raise HearthError("This connector does not have a Hearth chat adapter.")
        if provider not in self.selected:
            raise HearthError("Authorize this connector in Fly, then re-scan.")
        default = self.configured_entries(self.config).get(provider, {}).get("model", "")
        model = model.strip() or default
        if not valid_model(model):
            raise HearthError("Enter a model ID using letters, digits, and model path punctuation.")
        return {"provider": provider, "model": model}

    def brain_models(self, provider):
        if not isinstance(provider, str) or provider not in self.selected:
            raise HearthError("Authorize this connector in Fly, then re-scan.")
        if provider not in MODELS_PATHS:
            return {"models": [], "detail": "Model discovery is unavailable. Enter a model ID."}
        try:
            models = list_chat_models(self.gateway, self.gateway_entry(provider, self.selected[provider]))
        except ConnectorError:
            return {"models": [], "detail": "Could not load models. Enter a model ID."}
        return {"models": models, "detail": "" if models else "No chat models listed. Enter a model ID.",
                "tags": {model: router.model_tags({"provider": provider, "model": model},
                                                 self.config.get("brain_tags", {})) for model in models}}

    def save_brain(self, selection, pool):
        config = self.load()
        if config != self.config:
            raise HearthError("Saved connection settings changed. Re-scan and try again.")
        if selection != config["brain"] or (pool is not None and pool != config["brain_pool"]):
            config["brain"] = selection
            if pool is not None:
                config["brain_pool"] = pool
            self.persist(config, "Before saving Hearth brain settings")
            self.config = config

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
                "can_test": provider in self.selected,
                "uses": connector_uses(provider),
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
                if provider == "box" and old != connection_id:
                    config["box_folders"] = {}
        try:
            if config != previous:
                self.persist(config, "Before updating discovered Hearth connections")
        except HearthError as error:
            self.scan_error = str(error)
            return False
        self.checks = {provider: check for provider, check in self.checks.items()
                       if provider in selected and selected[provider] == self.selected.get(provider)}
        self.check_times = {provider: at for provider, at in self.check_times.items() if provider in self.checks}
        self.config, self.selected = config, selected
        self.found, self.available = found, set(authorized)
        self.last_scan = iso()
        self.scan_error = None
        return True

    def test(self, provider):
        if not isinstance(provider, str) or provider not in self.selected:
            raise HearthError("Authorize this connector in Fly, then re-scan.")
        connection_id = self.selected[provider]
        if catalog_entry(provider)["test_path"]:
            settings = self.config[provider] if provider in SETTINGS else {}
            self.checks[provider] = probe(self.gateway, {**settings, **self.gateway_entry(provider, connection_id)})
        else:
            self.checks[provider] = self.test_authorization(provider, connection_id)
        self.check_times[provider] = iso()

    def test_authorization(self, provider, connection_id):
        try:
            authorized, _ = self.gateway.discover()
        except ConnectorError:
            return "failed", "Hearth could not check gateway authorization. Try again from the Sprite."
        if connection_id not in authorized.get(provider, ()):
            return "denied", "The gateway no longer lists this connection. Refresh to update the catalog."
        return "passed", "The gateway confirmed this Sprite’s access."

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
        if provider == "pinecone":
            for key in ("host", "embedding_model"):
                config[provider].pop(key, None)
        config[provider][field] = value
        self.persist(config, "Before saving Hearth connection settings")
        self.config = config
        self.checks.pop(provider, None)
