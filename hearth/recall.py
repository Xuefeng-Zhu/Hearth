import hashlib
import json
import math
import re
import threading
import time
from urllib.parse import quote

from .connectors import ConnectorError
from .gateway_tools import redact_text
from .storage import HearthError, atomic_write
from .threads import Threads

MODELS = {
    "BAAI/bge-small-en-v1.5": "BGE Small · English",
    "BAAI/bge-base-en-v1.5": "BGE Base · English",
    "intfloat/multilingual-e5-base": "Multilingual E5 · Chinese and other languages",
}
FOLDERS = ("root", "people", "topics", "daily")
DEFAULTS = {
    "backend": "auto", "model": next(iter(MODELS)), "top_k": 5, "min_similarity": 0.55,
    "include_chat": False, "auto_remember": "off", "include": list(FOLDERS), "exclude": [],
}
BACKENDS = ("pinecone", "huggingface", "keyword")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
CITATION = re.compile(r"\[\[memory:([a-f0-9]{16})\]\]")
BATCH_SIZE = 16


def settings(values):
    if not isinstance(values, dict) or values.keys() - DEFAULTS.keys():
        raise HearthError("Invalid memory settings.")
    result = {**DEFAULTS, **values}
    if (result["backend"] not in ("auto", *BACKENDS) or result["model"] not in tuple(MODELS)
            or type(result["top_k"]) is not int or not 1 <= result["top_k"] <= 20
            or type(result["min_similarity"]) not in (int, float) or not 0 <= result["min_similarity"] <= 1
            or type(result["include_chat"]) is not bool
            or result["auto_remember"] not in ("off", "ask", "automatic")):
        raise HearthError("Choose a memory backend, model, top-k from 1–20, and similarity from 0–1.")
    for field in ("include", "exclude"):
        folders = result[field]
        if not isinstance(folders, list) or any(folder not in FOLDERS for folder in folders):
            raise HearthError("Choose valid memory folders.")
        result[field] = [folder for folder in FOLDERS if folder in folders]
    return result


def folder_allowed(path, selection):
    folder = path.split("/", 1)[0] if "/" in path else "root"
    return folder in selection["include"] and folder not in selection["exclude"]


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk(path, line, end_line, excerpt, heading="", **fields):
    excerpt = redact_text(excerpt).strip()
    heading = redact_text(heading)[:240]
    identity = fields.get("message_id") or str(line)
    return {"id": digest(f"{path}\n{identity}\n{excerpt}")[:16], "path": path, "line": line,
            "end_line": end_line, "excerpt": excerpt, "heading": heading, **fields}


def note_chunks(path, content):
    heading, heading_line = "", None
    lines = []

    def paragraph():
        text = "\n".join(value for _, value in lines).strip()
        if text:
            return chunk(path, lines[0][0], lines[-1][0], text, heading)

    for number, line in enumerate(content.splitlines(), 1):
        match = HEADING.match(line)
        if match or not line.strip() or (lines and sum(len(value) + 1 for _, value in lines) + len(line) > 1_000):
            if item := paragraph():
                yield item
                heading_line = None
            lines.clear()
        if match:
            if heading_line:
                yield chunk(path, heading_line, heading_line, heading)
            heading, heading_line = match[1], number
        elif line.strip():
            if len(line) > 1_000:
                # A source line stays intact so Forget removes exactly the cited source.
                yield chunk(path, number, number, line, heading)
                heading_line = None
            else:
                lines.append((number, line))
    if item := paragraph():
        yield item
    elif heading_line:
        yield chunk(path, heading_line, heading_line, heading)


def vector_text(item):
    return "\n".join(filter(None, (item["heading"], item["excerpt"])))[:1_200]


def ranked_hits(items, query, selection, similarities=None):
    words = set(re.findall(r"\w+", query.casefold()))
    hits = []
    for item in items:
        bag = set(re.findall(r"\w+", f"{item['path']} {vector_text(item)}".casefold()))
        keyword = len(words & bag) / max(len(words), 1)
        similarity = None if similarities is None else similarities.get(item["id"])
        if similarity is None:
            if not keyword or similarities is not None:
                continue
            score = keyword
        else:
            if similarity < selection["min_similarity"]:
                continue
            score = 0.8 * similarity + 0.2 * keyword
        hits.append({**item, "excerpt": item["excerpt"][:1_000], "score": round(score, 4),
                     "similarity": None if similarity is None else round(similarity, 4),
                     "keyword": round(keyword, 4), "citation": f"[[memory:{item['id']}]]"})
    return sorted(hits, key=lambda hit: -hit["score"])[:selection["top_k"]]


def normalized(vector):
    if not isinstance(vector, list) or not vector or any(type(x) not in (int, float) for x in vector):
        raise ConnectorError("The embedding provider returned an invalid vector.")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or not norm:
        raise ConnectorError("The embedding provider returned an invalid vector.")
    return [value / norm for value in vector]


class Recall:
    def __init__(self, storage, gateway):
        self.storage = storage
        self.gateway = gateway
        self.threads = Threads(storage)
        self.lock = threading.Lock()

    def hf_entry(self, config):
        return config.get("gateway", {}).get("huggingface") or next(
            (model for model in config["llm"] if model["provider"] == "huggingface" and model["connection_id"]), None)

    def available(self, config):
        return {"keyword": True, "huggingface": bool(self.hf_entry(config)),
                "pinecone": bool(config.get("pinecone", {}).get("connection_id"))}

    def backends(self, config, selection):
        available = self.available(config)
        preferred = BACKENDS if selection["backend"] == "auto" else (selection["backend"], "keyword")
        return list(dict.fromkeys(backend for backend in preferred if available[backend]))

    def items(self, selection):
        with self.storage.lock():
            items = [item for path in self.storage.files() if folder_allowed(path, selection)
                     for item in note_chunks(path, self.storage.read(path))]
            if not selection["include_chat"]:
                return items
            forgotten = set(self.storage.load().get("forgotten_chat", []))
            for thread in self.threads.list():
                path = f"chat/{thread['id']}"
                for line, message in enumerate(self.threads.messages(thread["id"]), 1):
                    identity = message.get("id") or f"{thread['id']}:{line}"
                    if message["role"] == "call" or identity in forgotten or not message["content"].strip():
                        continue
                    items.append(chunk(path, line, line, message["content"], thread["title"],
                                       thread_id=thread["id"], message_id=identity))
            return items

    def embed(self, config, source, model, texts, kind):
        if source == "huggingface":
            if model.startswith("intfloat/"):
                texts = [f"{kind}: {text}" for text in texts]
            elif kind == "query":
                texts = [f"Represent this sentence for searching relevant passages: {text}" for text in texts]
            path = f"hf-inference/models/{quote(model, safe='/')}/pipeline/feature-extraction"
            records = self.gateway.json(self.hf_entry(config), path, {"inputs": texts}, allow_array=True)
        else:
            response = self.gateway.json(config["pinecone"], "embed", {
                "model": model, "inputs": [{"text": text} for text in texts],
                "parameters": {"input_type": kind, "truncate": "END"},
            })
            try:
                records = [record["values"] for record in response["data"]]
            except (KeyError, TypeError):
                raise ConnectorError("Pinecone returned an invalid embedding response.") from None
        if not isinstance(records, list) or len(records) != len(texts):
            raise ConnectorError("The provider returned the wrong number of embeddings.")
        vectors = [normalized(vector) for vector in records]
        if len({len(vector) for vector in vectors}) != 1:
            raise ConnectorError("The provider returned mixed embedding dimensions.")
        return vectors

    def vector_index(self, config, selection, backend, checkpoint, progress, rebuild, query):
        pinecone = config.get("pinecone", {})
        sources = [("huggingface", selection["model"])]
        if backend == "pinecone":
            sources.insert(0, ("pinecone", pinecone["model"]))
            if not self.hf_entry(config):
                sources.pop()
        for index, (source, model) in enumerate(sources):
            try:
                with self.lock:
                    items = self.items(selection)
                    vectors, namespace, stats = self.sync(config, backend, source, model, items, checkpoint, progress, rebuild)
                scores = self.query_scores(config, backend, source, model, items, vectors, namespace, query)
                return items, scores, stats
            except ConnectorError:
                if index == len(sources) - 1:
                    raise

    def sync(self, config, backend, source, model, items, checkpoint, progress, rebuild):
        pinecone = config.get("pinecone", {})
        entry = self.hf_entry(config) if source == "huggingface" else pinecone
        identity = [2, source, model, entry["connection_id"]]
        if backend == "pinecone":
            identity.extend(pinecone[key] for key in ("connection_id", "index", "namespace"))
        index_id = digest(json.dumps(identity))[:24]
        path = self.storage.live / "index" / f"{index_id}.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            saved = {}
        previous = saved.get("vectors", {})
        vectors = {} if rebuild else previous.copy()
        indexed = set(saved.get("remote", []))
        texts = {digest(vector_text(item)): vector_text(item) for item in items}
        missing = [key for key in texts if key not in vectors]
        remote = backend == "pinecone"
        remote_path = f"indexes/{quote(pinecone.get('index', ''), safe='')}"
        dimension = saved.get("dimension")
        if remote and (rebuild or not saved) and items:
            descriptor = self.gateway.json(pinecone, remote_path)
            dimension = descriptor.get("dimension")
            if descriptor.get("metric") not in (None, "cosine"):
                raise ConnectorError("This Pinecone index must use cosine similarity.")
            if checkpoint:
                checkpoint("Before syncing memory to Pinecone")
        embedded = 0
        if progress:
            progress(total=len(items), unique=len(texts), embedded=0, reused=len(texts) - len(missing), backend=backend)
        for start in range(0, len(missing), BATCH_SIZE):
            batch = missing[start:start + BATCH_SIZE]
            for key, vector in zip(batch, self.embed(config, source, model, [texts[key] for key in batch], "passage")):
                vectors[key] = vector
            embedded += len(batch)
            if progress:
                progress(embedded=embedded)
        vectors = {key: vectors[key] for key in texts}
        namespace = f"{pinecone.get('namespace', 'hearth')}-{digest(str(self.storage.root))[:12]}-{index_id}"
        if remote:
            if dimension and any(len(vector) != dimension for vector in vectors.values()):
                raise ConnectorError(f"The embedding model does not match the {dimension}-dimension Pinecone index.")
            upserts = list(vectors) if rebuild else [key for key in vectors if key not in indexed]
            for start in range(0, len(upserts), BATCH_SIZE):
                self.gateway.json(pinecone, f"{remote_path}/vectors/upsert", {"namespace": namespace, "vectors": [
                    {"id": key, "values": vectors[key]} for key in upserts[start:start + BATCH_SIZE]
                ]})
            deleted = sorted(indexed - vectors.keys())
            for start in range(0, len(deleted), 100):
                self.gateway.json(pinecone, f"{remote_path}/vectors/delete",
                                  {"namespace": namespace, "ids": deleted[start:start + 100]})
        state = {"vectors": vectors, "remote": list(vectors) if remote else [], "dimension": dimension}
        if state != saved:
            atomic_write(path, json.dumps(state, separators=(",", ":")))
        stats = {"total": len(items), "unique": len(texts), "embedded": embedded, "reused": len(texts) - len(missing)}
        return vectors, namespace, stats

    def query_scores(self, config, backend, source, model, items, vectors, namespace, query):
        if query is None or not vectors:
            return {}
        query_vector, = self.embed(config, source, model, [query], "query")
        try:
            similarities = {key: sum(x * y for x, y in zip(vector, query_vector, strict=True))
                            for key, vector in vectors.items()}
        except ValueError:
            raise ConnectorError("The query and index have different embedding dimensions. Reindex memory.") from None
        if backend == "pinecone":
            pinecone = config["pinecone"]
            index = quote(pinecone["index"], safe="")
            response = self.gateway.json(pinecone, f"indexes/{index}/query", {
                "namespace": namespace, "vector": query_vector, "topK": min(len(vectors), 40),
            })
            matches = response.get("matches")
            if not isinstance(matches, list):
                raise ConnectorError("Pinecone returned invalid search results.")
            for match in matches:
                if not isinstance(match, dict):
                    continue
                key, score = match.get("id"), match.get("score")
                if isinstance(key, str) and key in similarities and type(score) in (int, float) and math.isfinite(score):
                    similarities[key] = score
        return {item["id"]: similarities[digest(vector_text(item))] for item in items}

    def forget_vectors(self, items):
        keys = {digest(vector_text(item)) for item in items}
        for path in (self.storage.live / "index").glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                vectors = data.get("vectors", {})
                if keys.intersection(vectors):
                    data["vectors"] = {key: value for key, value in vectors.items() if key not in keys}
                    atomic_write(path, json.dumps(data, separators=(",", ":")))
            except (OSError, ValueError):
                # The corpus still excludes the forgotten item even if its cache cannot be rewritten.
                continue

    def run(self, config, selection, query=None, *, checkpoint=None, progress=None, rebuild=False, skip_message=None):
        start = time.monotonic()
        warnings = []
        available = self.available(config)
        requested = selection["backend"]
        if requested not in ("auto", "keyword") and not available[requested]:
            name = "Pinecone" if requested == "pinecone" else "Hugging Face"
            warnings.append(f"{name} is disconnected. Using Keyword.")
        for backend in self.backends(config, selection):
            if backend == "keyword":
                items = self.items(selection)
                similarities = None
                stats = {"total": len(items), "unique": 0, "embedded": 0, "reused": 0}
            else:
                try:
                    items, similarities, stats = self.vector_index(
                        config, selection, backend, checkpoint, progress, rebuild, query)
                except (ConnectorError, OSError) as error:
                    status = getattr(error, "status", None)
                    name = "Pinecone" if backend == "pinecone" else "Hugging Face"
                    detail = f"The gateway returned HTTP {status}." if status else (
                        str(error) if isinstance(error, ConnectorError) else "The local index could not be saved.")
                    warnings.append(f"{name} recall failed. {detail}")
                    continue
            candidates = [item for item in items if not skip_message or item.get("message_id") != skip_message]
            hits = ranked_hits(candidates, query, selection, similarities) if query is not None else []
            return {"backend": backend, "results": hits, "warnings": warnings, **stats,
                    "latency_ms": round((time.monotonic() - start) * 1_000)}
