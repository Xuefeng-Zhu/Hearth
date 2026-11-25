import hashlib
import json
import math
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from urllib.parse import quote

from . import pinecone
from .connectors import ConnectorError
from .gateway_tools import redact_text
from .storage import HearthError, atomic_write, iso
from .threads import MAIN, Threads

MODELS = {
    "BAAI/bge-small-en-v1.5": "BGE Small · English",
    "BAAI/bge-base-en-v1.5": "BGE Base · English",
    pinecone.DENSE_MODEL: "Multilingual E5 Small · multilingual",
    "intfloat/multilingual-e5-base": "Multilingual E5 · Chinese and other languages",
}
FOLDERS = ("root", "people", "topics", "daily")
DEFAULTS = {
    "backend": "auto", "model": next(iter(MODELS)), "top_k": 8, "min_similarity": 0.55,
    "include_chat": False, "auto_remember": "off", "include": list(FOLDERS), "exclude": [],
}
BACKENDS = ("pinecone", "local", "huggingface", "keyword")
KINDS = ("fact", "preference", "person", "event", "artifact", "transcript")
CHAT_BUDGET = 0.55
QUERY_CACHE_SIZE = 128
QUERY_FILLERS = {"a", "an", "can", "cannot", "do", "does", "is", "of", "the", "to", "what", "who", "who's"}
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
    identity = fields.get("message_id") or str(fields.get("part", line))
    return {"id": digest(f"{path}\n{identity}\n{excerpt}")[:16], "path": path, "line": line,
            "end_line": end_line, "excerpt": excerpt, "heading": heading, **fields}


def note_chunks(path, content, **fields):
    heading, heading_line = "", None
    lines = []

    def paragraph():
        text = "\n".join(value for _, value in lines).strip()
        if text:
            return chunk(path, lines[0][0], lines[-1][0], text, heading, **fields)

    for number, line in enumerate(content.splitlines(), 1):
        match = HEADING.match(line)
        if match or not line.strip() or (lines and sum(len(value) + 1 for _, value in lines) + len(line) > 1_000):
            if item := paragraph():
                yield item
                heading_line = None
            lines.clear()
        if match:
            if heading_line:
                yield chunk(path, heading_line, heading_line, heading, **fields)
            heading, heading_line = match[1], number
        elif line.strip():
            if len(line) > 1_000:
                # A source line stays intact so Forget removes exactly the cited source.
                yield chunk(path, number, number, line, heading, **fields)
                heading_line = None
            else:
                lines.append((number, line))
    if item := paragraph():
        yield item
    elif heading_line:
        yield chunk(path, heading_line, heading_line, heading, **fields)


def vector_text(item):
    return redact_text("\n".join(filter(None, (item["heading"], item["excerpt"]))))[:1_200]


def note_kind(item):
    if item["path"].startswith("people/"):
        return "person"
    heading = item["heading"].casefold()
    excerpt = item["excerpt"].casefold().lstrip("-* ")
    if (re.search(r"preferences?|偏好|likes|dislikes", heading)
            or re.match(r"(?:i |we )?prefer\b", excerpt)):
        return "preference"
    if re.search(r"thanksgiving|event|schedule|节日", heading):
        return "event"
    return "fact"


def filters_from(values):
    if not isinstance(values, dict) or values.keys() - {"kind", "thread_id"}:
        raise HearthError("Filter recall by kind or thread.")
    if "kind" in values and values["kind"] not in KINDS:
        raise HearthError("Choose a valid memory kind.")
    if "thread_id" in values and not (isinstance(values["thread_id"], str) and
                                       re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", values["thread_id"])):
        raise HearthError("Choose a valid chat thread.")
    return values


def chat_text(message):
    if message["role"] != "call":
        return message["content"]
    return "\n".join(f"{entry['role']}: {entry['text']}" for entry in message.get("lines", []))


def metadata(item):
    return {key: redact_text(str(value)) for key, value in {
        "memory_id": item["id"], "kind": item.get("kind") or note_kind(item),
        "thread_id": item.get("thread_id") or item.get("origin_thread") or MAIN, "created_at": item["created_at"],
        "source": item["source"], "text": vector_text(item),
        "scope": item["scope"],
    }.items()}


def artifact_chunks(rows):
    for row in rows:
        if row.get("deleted") or not row.get("content"):
            continue
        # Bound embedding input while retaining consecutive sections of long files.
        content = redact_text(row["content"])
        for start in range(0, len(content), 1_000):
            excerpt = content[start:start + 1_000]
            if excerpt.strip():
                line = content.count("\n", 0, start) + 1
                yield chunk(f"artifacts/{row['id']}", line, line + excerpt.count("\n"), excerpt, row["title"],
                            kind="artifact", source="Box" if row.get("box_id") else "Artifact",
                            scope="artifacts", artifact_id=row["id"], part=start,
                            created_at=row.get("created_at") or "",
                            **({"thread_id": row["thread_id"]} if row.get("thread_id") else {}))



def ranked_hits(items, query, selection, similarities=None):
    words = set(re.findall(r"\w+(?:['’]\w+)*", query.casefold())) - QUERY_FILLERS
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
        self.on_change = None
        self.remote = None
        self.remote_status = {}
        self.query_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pinecone-recall")
        self.query_slots = threading.BoundedSemaphore(4)
        self.query_cache = OrderedDict()
        self.query_cache_lock = threading.Lock()
        self.box_path = self.storage.live / "index" / "box-artifacts.json"

    def changed(self):
        if self.on_change:
            self.on_change()

    def hf_entry(self, config):
        return config.get("gateway", {}).get("huggingface") or next(
            (model for model in config["llm"] if model["provider"] == "huggingface" and model["connection_id"]), None)

    def available(self, config):
        return {"local": True, "keyword": True, "huggingface": bool(self.hf_entry(config)),
                "pinecone": bool(config.get("pinecone", {}).get("connection_id"))}

    @staticmethod
    def target(config):
        entry = config.get("pinecone", {})
        return tuple(entry.get(key) for key in ("connection_id", "index", "namespace"))

    def pinecone_status(self, config):
        connection_id, name, namespace = self.target(config)
        default = {"name": name, "namespace": namespace, "connected": bool(connection_id),
                   "record_count": None, "last_sync": None}
        if connection_id and self.remote_status.get("target") == self.target(config):
            return {**default, **{key: value for key, value in self.remote_status.items() if key != "target"}}
        return default

    @staticmethod
    def read_index(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def replace_box_artifacts(self, rows):
        atomic_write(self.box_path, json.dumps(rows, ensure_ascii=False))

    def items(self, selection, box_connection=None, box_folder=None):
        with self.storage.lock():
            state = self.storage.load()
            origins = state.get("memory_origins", {})
            items = []
            for path in self.storage.files():
                if not folder_allowed(path, selection):
                    continue
                file = self.storage.memory_path(path)
                origin = origins.get(path, {})
                created_at = origin.get("created_at") or iso(datetime.fromtimestamp(file.stat().st_mtime, timezone.utc))
                scope = path.split("/", 1)[0] if "/" in path else "root"
                for item in note_chunks(path, redact_text(self.storage.read(path)), created_at=created_at, source="Markdown", scope=scope):
                    excerpt_origin = origin.get("excerpts", {}).get(item["id"], origin)
                    item.update(kind=note_kind(item), origin_thread=excerpt_origin.get("thread_id") or MAIN,
                                created_at=excerpt_origin.get("created_at") or created_at)
                    items.append(item)
            rows = state.get("artifacts", {})
            cache = self.read_index(self.box_path)
            box_rows = cache.get("rows", {}) if cache.get("scope") == [box_connection, box_folder] else {}
            merged = {key: row for key, row in box_rows.items()}
            merged.update(rows)
            for identity, row in box_rows.items():
                if identity in rows and rows[identity].get("sync") == "synced" and not rows[identity].get("deleted"):
                    merged[identity] = {**rows[identity], **row}
            items.extend(artifact_chunks(merged.values()))
            if selection["include_chat"]:
                forgotten = set(state.get("forgotten_chat", []))
                for thread in self.threads.list():
                    path = f"chat/{thread['id']}"
                    for line, message in enumerate(self.threads.messages(thread["id"]), 1):
                        identity = message.get("id") or f"{thread['id']}:{line}"
                        text = chat_text(message)
                        if identity in forgotten or not text.strip():
                            continue
                        items.append(chunk(path, line, line, text, thread["title"],
                                           thread_id=thread["id"], message_id=identity, kind="transcript",
                                           scope="chat", source="Voice transcript" if message["role"] == "call" else "Chat",
                                           created_at=message.get("at") or ""))
            return items

    def corpus(self, config, selection):
        box_entry = config.get("gateway", {}).get("box", {})
        return self.items(selection, box_entry.get("connection_id"), config.get("artifacts", {}).get("folder_name"))

    def embed(self, config, model, texts, kind, *, timeout=25):
        if model.startswith("intfloat/"):
            texts = [f"{kind}: {text}" for text in texts]
        elif kind == "query":
            texts = [f"Represent this sentence for searching relevant passages: {text}" for text in texts]
        path = f"hf-inference/models/{quote(model, safe='/')}/pipeline/feature-extraction"
        entry = self.hf_entry(config)
        if not entry:
            raise ConnectorError("Hugging Face is disconnected.")
        records = self.gateway.json(entry, path, {"inputs": texts}, allow_array=True, timeout=timeout)
        if not isinstance(records, list) or len(records) != len(texts):
            raise ConnectorError("The provider returned the wrong number of embeddings.")
        vectors = [normalized(vector) for vector in records]
        if len({len(vector) for vector in vectors}) != 1:
            raise ConnectorError("The provider returned mixed embedding dimensions.")
        return vectors

    def embed_pinecone_query(self, config, model, texts, kind, *, timeout):
        entry = self.hf_entry(config)
        if not entry:
            raise ConnectorError("Hugging Face is disconnected.")
        key = (entry["connection_id"], model, digest(texts[0]))
        with self.query_cache_lock:
            if key in self.query_cache:
                self.query_cache.move_to_end(key)
                return self.query_cache[key]
        vectors = self.embed(config, model, texts, kind, timeout=timeout)
        with self.query_cache_lock:
            self.query_cache[key] = vectors
            self.query_cache.move_to_end(key)
            if len(self.query_cache) > QUERY_CACHE_SIZE:
                self.query_cache.popitem(last=False)
        return vectors

    def local_vectors(self, config, selection, items, progress, rebuild, query):
        model = selection["model"]
        index_id = digest(json.dumps([2, "huggingface", model, self.hf_entry(config)["connection_id"]]))[:24]
        path = self.storage.live / "index" / f"{index_id}.json"
        with self.lock:
            saved = self.read_index(path)
            texts = {digest(vector_text(item)): vector_text(item) for item in items}
            vectors = {} if rebuild else {key: value for key, value in saved.get("vectors", {}).items() if key in texts}
            missing = [key for key in texts if key not in vectors]
            stats = {"total": len(items), "unique": len(texts), "embedded": 0, "reused": len(vectors)}
            if progress:
                progress(**stats, backend="huggingface")
            for offset in range(0, len(missing), BATCH_SIZE):
                batch = missing[offset:offset + BATCH_SIZE]
                embedded = self.embed(config, model, [texts[key] for key in batch], "passage")
                vectors.update(zip(batch, embedded, strict=True))
                stats["embedded"] += len(batch)
                if progress:
                    progress(embedded=stats["embedded"])
            if vectors != saved.get("vectors", {}):
                atomic_write(path, json.dumps({"vectors": vectors}, separators=(",", ":")))
        if query is None or not vectors:
            return {}, stats
        query_vector, = self.embed(config, model, [query], "query")
        try:
            scores = {key: sum(x * y for x, y in zip(vector, query_vector, strict=True))
                      for key, vector in vectors.items()}
        except ValueError:
            raise ConnectorError("The query and index have different embedding dimensions. Reindex memory.") from None
        return {item["id"]: scores[digest(vector_text(item))] for item in items}, stats

    def sync_pinecone(self, config, selection, *, progress, save_index=None, rebuild=False, inspect=False):
        entry = config["pinecone"]
        target = self.target(config)
        index = pinecone.Index(self.gateway, entry)
        path = self.storage.root / "pinecone-sync" / f"{digest(json.dumps(target))[:24]}.json"
        saved = self.read_index(path)
        if self.remote and self.remote[0] == target:
            index.rerank_unavailable = self.remote[1].rerank_unavailable
            index.vector_transport = self.remote[1].vector_transport
        else:
            index.vector_transport = bool(saved.get("vector_transport"))
        self.remote_status = {"target": target, "last_sync": saved.get("last_sync"), "state": "Connecting"}
        try:
            info = index.bootstrap(bool(self.hf_entry(config)))
            remote = (target, index, info)
            if info["host"] != saved.get("host"):
                index.vector_transport = False
            if save_index:
                save_index(entry, info)
            count = index.stats()
            self.remote_status = {**self.remote_status, **info, "record_count": count, "state": "Ready"}
            records = {item["id"]: metadata(item) for item in self.corpus(config, selection)}
            fingerprints = {key: digest(json.dumps(row, sort_keys=True)) for key, row in records.items()}
            owned = set(saved.get("known", [])) | saved.get("records", {}).keys()
            known = index.list_ids() if (inspect or rebuild) and count else None
            if known is not None:
                owned.update(key for key in known if re.fullmatch(r"[a-f0-9]{16}", key))
            previous = saved.get("records", {}) if count and not rebuild and info["host"] == saved.get("host") else {}
            missing = [key for key, fingerprint in fingerprints.items()
                       if previous.get(key) != fingerprint or (known is not None and key not in known)]
            stale = sorted(owned - records.keys()) if count or not inspect else []
            stats = {"total": len(records), "upserted": 0, "deleted": 0, "unchanged": len(records) - len(missing),
                     "work": len(missing) + len(stale)}
            progress(**stats)
            # Keep all in-flight IDs so a crash after a write can be reconciled.
            if missing or stale:
                pending = {**saved, "known": sorted(owned | records.keys())}
                atomic_write(path, json.dumps(pending, separators=(",", ":")))
            embed = lambda model, texts, kind, **kwargs: self.embed(config, model, texts, kind, **kwargs)
            for offset in range(0, len(stale), 100):
                batch = stale[offset:offset + 100]
                index.delete(batch)
                stats["deleted"] += len(batch)
                progress(deleted=stats["deleted"])
            for offset in range(0, len(missing), pinecone.BATCH_SIZE):
                batch = missing[offset:offset + pinecone.BATCH_SIZE]
                index.upsert(info, [records[key] for key in batch], embed)
                stats["upserted"] += len(batch)
                progress(upserted=stats["upserted"])
            last_sync = iso() if inspect or rebuild or stats["work"] else saved.get("last_sync")
            atomic_write(path, json.dumps({"records": fingerprints, "host": info["host"], "last_sync": last_sync,
                                          "vector_transport": index.vector_transport}, separators=(",", ":")))
            self.remote = remote
            if stats["work"]:
                for delay in (0, 0.25, 0.6, 1):
                    if delay:
                        time.sleep(delay)
                    count = index.stats()
                    if count == len(records):
                        break
            self.remote_status = {**self.remote_status, "record_count": count, "last_sync": last_sync,
                                  "state": "Ready", "vector_transport": index.vector_transport}
            return {**stats, "record_count": count}
        except (ConnectorError, OSError) as error:
            self.remote_status = {**self.remote_status, "state": "Unavailable",
                                  "error": error_message(error)}
            raise

    def pinecone_hits(self, config, selection, query, candidates, filters, budget):
        current = self.remote
        if not current or current[0] != self.target(config):
            raise ConnectorError(self.pinecone_status(config).get("error") or "The Pinecone index is preparing.")
        _, index, info = current
        scope = [folder for folder in selection["include"] if folder not in selection["exclude"]]
        scope += ["artifacts"] + (["chat"] if selection["include_chat"] else [])
        constraints = {field: {"$eq": value} for field, value in filters.items()}
        constraints["scope"] = {"$in": scope}
        deadline = time.monotonic() + budget
        def embed(model, texts, kind, *, timeout):
            return self.embed_pinecone_query(config, model, texts, kind, timeout=timeout)

        initial = None

        def search():
            nonlocal initial
            matches = index.query(info, query, selection["top_k"], constraints, embed, deadline)
            hits = [{**candidates[key], "excerpt": candidates[key]["excerpt"][:1_000], "backend": "pinecone",
                     "score": round(score, 4), "similarity": round(score, 4),
                     "citation": f"[[memory:{key}]]"}
                    for key, score in matches if key in candidates and score >= selection["min_similarity"]]
            initial = hits
            reranked, used = index.rerank(query, hits, deadline)
            return reranked, used

        if budget <= 0 or not self.query_slots.acquire(blocking=False):
            raise ConnectorError("Pinecone exceeded the recall time budget.", 504)
        future = self.query_pool.submit(search)
        future.add_done_callback(lambda _: self.query_slots.release())
        try:
            return future.result(timeout=pinecone.remaining(deadline))
        except FutureTimeout:
            future.cancel()
            if initial is not None:
                return initial, False
            raise ConnectorError("Pinecone exceeded the recall time budget.", 504) from None

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

    def run(self, config, selection, query=None, *, progress=None, rebuild=False, skip_message=None,
            filters=None, budget=CHAT_BUDGET):
        start = time.monotonic()
        query = redact_text(query) if query is not None else None
        filters = filters_from(filters or {})
        warnings = []
        requested = selection["backend"]
        items = self.corpus(config, selection)
        candidates = {item["id"]: item for item in items if (not skip_message or item.get("message_id") != skip_message)
                      and all(metadata(item)[key] == value for key, value in filters.items())}
        stats = {"total": len(items), "unique": 0, "embedded": 0, "reused": 0}
        backend = "keyword" if requested == "keyword" else "local"
        similarities = None
        hits, reranked = [], False
        if requested in ("auto", "pinecone") and query is not None:
            if self.available(config)["pinecone"]:
                try:
                    elapsed = time.monotonic() - start
                    hits, reranked = self.pinecone_hits(config, selection, query, candidates, filters, budget - elapsed)
                    backend = "pinecone"
                except ConnectorError as error:
                    warnings.append(f"Pinecone recall unavailable. {error_message(error)}")
            elif requested == "pinecone":
                warnings.append("Pinecone is disconnected. Using Local.")
        if requested == "huggingface" or (query is None and rebuild and self.hf_entry(config)):
            if self.hf_entry(config):
                try:
                    similarities, stats = self.local_vectors(config, selection, items, progress, rebuild, query)
                    backend = "huggingface"
                except (ConnectorError, OSError) as error:
                    warnings.append(f"Hugging Face recall failed. {error_message(error)}")
            else:
                warnings.append("Hugging Face is disconnected. Using Local.")
        if backend != "pinecone" and query is not None:
            hits = [{**hit, "backend": backend} for hit in ranked_hits(candidates.values(), query, selection, similarities)]
        return {"backend": backend, "results": hits, "warnings": warnings, "reranked": reranked, **stats,
                "latency_ms": round((time.monotonic() - start) * 1_000)}


def error_message(error):
    if isinstance(error, ConnectorError):
        message = redact_text(str(error))
        if error.status and f"HTTP {error.status}" not in message and error.status != 504:
            return f"{message} HTTP {error.status}."
        return message
    return "Hearth could not save the memory index."
