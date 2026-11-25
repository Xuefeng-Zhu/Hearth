import hashlib
import json
import os
import re
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .storage import HearthError, ROOT

GATEWAY = "https://api.sprites.dev/v1/gateway"
GATEWAY_SEGMENT = re.compile(r"[a-zA-Z0-9_-]+")
DISCOVERY_PROVIDERS = ("meta", "pinecone", "tavily", "agentmail")
MODEL_PATHS = {"meta": "v1/chat/completions", "ollama": "v1/chat/completions",
               "openrouter": "api/v1/chat/completions"}
PINECONE_HEADERS = {"X-Pinecone-Api-Version": "2025-10"}


class ConnectorError(HearthError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Gateway:
    def __init__(self):
        self.opener = build_opener(NoRedirect())

    def open(self, config, path, body=None, headers=None, *, timeout=25):
        provider = config["provider"]
        connection_id = config["connection_id"]
        if not all(GATEWAY_SEGMENT.fullmatch(part) for part in (provider, connection_id)):
            raise ConnectorError("Invalid connector configuration.")
        return self.request(f"{provider}/{connection_id}/{path}", body, headers, timeout)

    def request(self, path, body, headers, timeout):
        request = Request(
            f"{GATEWAY}/{path}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={key: value for key, value in (headers or {}).items()
                     if key.lower() in {"accept", "idempotency-key", "x-pinecone-api-version"}},
        )
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            return self.opener.open(request, timeout=timeout)
        except HTTPError as error:
            error.close()
            raise ConnectorError("The gateway rejected the request.", error.code) from None
        except (HTTPException, URLError, OSError):
            raise ConnectorError("The gateway is unavailable.") from None

    def json(self, config, path, body=None, headers=None, *, timeout=25):
        return self.read_json(self.open(config, path, body, headers, timeout=timeout))

    @staticmethod
    def read_json(response):
        try:
            with response:
                data = json.loads(response.read(8 * 1024 * 1024))
        except (HTTPException, OSError, ValueError):
            raise ConnectorError("The connector returned an unreadable response.") from None
        if not isinstance(data, dict):
            raise ConnectorError("The connector returned an unexpected response.")
        return data

    def discover(self):
        data = self.read_json(self.request("list", None, None, 8))
        entries = data.get("connections")
        if not isinstance(entries, list):
            raise ConnectorError("The gateway returned an unreadable connection list.")
        authorized = {provider: [] for provider in DISCOVERY_PROVIDERS}
        found = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            provider = entry.get("provider")
            if provider not in DISCOVERY_PROVIDERS:
                continue
            found.add(provider)
            if entry.get("authorized") is False:
                continue
            base = entry.get("gateway_base_url")
            prefix = f"/v1/gateway/{provider}/"
            try:
                url = urlsplit(base) if isinstance(base, str) else None
            except ValueError:
                url = None
            if not url or (url.scheme, url.netloc) != ("https", "api.sprites.dev") or url.query or url.fragment:
                continue
            if url.path.rstrip("/") == prefix.rstrip("/"):
                connection_id = entry.get("connection_id", entry.get("id"))
            elif url.path.startswith(prefix):
                connection_id = url.path.removeprefix(prefix).removesuffix("/")
            else:
                continue
            if isinstance(connection_id, str) and GATEWAY_SEGMENT.fullmatch(connection_id):
                authorized[provider].append(connection_id)
        # The available array is a provider catalog, not a list of organization connections.
        return authorized, found

    def completion(self, config, messages, tools, emit):
        text = []
        calls = {}
        finished = False
        try:
            with self.open(config, MODEL_PATHS[config["provider"]],
                           {"model": config["model"], "messages": messages, "tools": tools, "stream": True},
                           {"Accept": "text/event-stream"}) as response:
                for line in response:
                    line = line.strip()
                    if line == b"data: [DONE]":
                        finished = True
                        break
                    if not line.startswith(b"data:"):
                        continue
                    packet = json.loads(line[5:])
                    if packet.get("error"):
                        raise ConnectorError("The model connector returned an error.")
                    for choice in (packet.get("choices") or [])[:1]:
                        finished |= choice.get("finish_reason") is not None
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            text.append(delta["content"])
                            emit(delta["content"])
                        for part in delta.get("tool_calls") or ():
                            call = calls.setdefault(part["index"], {
                                "id": "", "type": "function", "function": {"name": "", "arguments": ""}
                            })
                            call["id"] += part.get("id") or ""
                            fragment = part.get("function") or {}
                            for key in ("name", "arguments"):
                                call["function"][key] += fragment.get(key) or ""
        except (HTTPException, OSError, ValueError, TypeError, KeyError):
            raise ConnectorError("The model stream was interrupted.") from None
        if not finished or not (text or calls):
            raise ConnectorError("The model connector returned an incomplete reply.")
        return {"role": "assistant", "content": "".join(text) or None,
                **({"tool_calls": [calls[index] for index in sorted(calls)]} if calls else {})}


def read_config(path=None):
    local = Path(os.environ.get("HEARTH_CONNECTOR_CONFIG", ROOT / "config/connectors.local.json"))
    file = Path(path) if path else local if local.is_file() else ROOT / "config/connectors.json"
    return json.loads(file.read_text(encoding="utf-8"))


class Integrations:
    def __init__(self, config, gateway=None):
        self.config = config
        self.gateway = gateway or Gateway()

    def configured(self, name):
        return bool(self.config.get(name, {}).get("connection_id"))

    def has_mail(self):
        return self.config.get("agentmail", {}).get("connection_id") and self.config["agentmail"].get("inbox_id")

    def send(self, action):
        config = self.config["agentmail"]
        inbox = quote(config["inbox_id"], safe="")
        data = self.gateway.json(
            config, f"v0/inboxes/{inbox}/messages/send",
            action["email"], {"Idempotency-Key": action["id"]},
        )
        if not data.get("message_id"):
            raise ConnectorError("AgentMail returned an unknown delivery status.")

    def search_web(self, query):
        if not self.configured("tavily"):
            raise HearthError("Web search needs a Tavily connector.")
        data = self.gateway.json(self.config["tavily"], "search", {"query": query, "max_results": 4})
        return [{key: str(result.get(key, ""))[:650] for key in ("title", "url", "content")}
                for result in data.get("results", [])[:4]]

    def recall(self, storage, checkpoint, query):
        if not self.configured("pinecone"):
            return storage.search(query)
        config = self.config["pinecone"]
        notes = {path: storage.read(path) for path in storage.files()}
        if not any(notes.values()):
            return storage.search(query)
        corpus = json.dumps(notes, ensure_ascii=False, sort_keys=True)
        revision = hashlib.sha256(corpus.encode("utf-8")).hexdigest()[:20]
        namespace = f"{config['namespace']}-{revision}"
        index = quote(config["index"], safe="")
        key = [config["connection_id"], config["index"], config["model"], namespace]
        state = storage.load()
        try:
            if key not in state["indexed"]:
                self.index_notes(config, checkpoint, notes, namespace, index)
                state["indexed"].append(key)
                storage.save(state)
            vector, = self.embed(config, [query], "query")
            data = self.gateway.json(config, f"indexes/{index}/query", {
                "namespace": namespace, "vector": vector, "topK": 12, "includeMetadata": True,
            }, PINECONE_HEADERS)
            hits = {}
            for match in data.get("matches", []):
                metadata = match.get("metadata", {})
                path = metadata.get("path")
                if path in notes:
                    hits.setdefault(path, {"path": path, "excerpt": metadata["excerpt"][:550]})
            return list(hits.values())[:5] or storage.search(query)
        except (HearthError, KeyError, TypeError, ValueError):
            return storage.search(query)

    def index_notes(self, config, checkpoint, notes, namespace, index):
        chunks = [
            (path, offset, content[offset:offset + 1200])
            for path, content in notes.items()
            for offset in range(0, len(content), 1200)
        ]
        checkpoint.create("Before syncing memory to Pinecone")
        for start in range(0, len(chunks), 32):
            batch = chunks[start:start + 32]
            vectors = self.embed(config, [text for _, _, text in batch], "passage")
            self.gateway.json(config, f"indexes/{index}/vectors/upsert", {
                "namespace": namespace,
                "vectors": [
                    {"id": f"{path}:{offset}", "values": vector, "metadata": {"path": path, "excerpt": text}}
                    for (path, offset, text), vector in zip(batch, vectors, strict=True)
                ],
            }, PINECONE_HEADERS)

    def embed(self, config, texts, input_type):
        result = self.gateway.json(config, "embed", {
            "model": config["model"], "inputs": [{"text": text} for text in texts],
            "parameters": {"input_type": input_type, "truncate": "END"},
        }, PINECONE_HEADERS)
        return [record["values"] for record in result["data"]]
