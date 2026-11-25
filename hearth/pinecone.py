"""Pinecone REST operations through the Sprite connector."""

import json
import math
import re
import time
from urllib.parse import quote, urlencode

from .connectors import ConnectorError
from .gateway_tools import redact_text

INDEX_HOST = re.compile(r"[a-z0-9][a-z0-9.-]*\.pinecone\.io")
NAMESPACE = re.compile(r"[a-zA-Z0-9_-]{1,128}")
DENSE_MODEL = "intfloat/multilingual-e5-small"
DENSE_DIMENSION = 384
RERANK_MODEL = "bge-reranker-v2-m3"
BATCH_SIZE = 32
BLOCKED = (400, 401, 403, 404, 405, 415, 422, 501)
TRANSIENT = (None, 408, 429, 500, 502, 503, 504)


def retry(operation):
    for delay in (0.15, 0.45, None):
        try:
            return operation()
        except ConnectorError as error:
            if delay is None or error.status not in TRANSIENT:
                raise
            time.sleep(delay)


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise ConnectorError("Pinecone exceeded the recall time budget.", 504)
    return seconds


class Index:
    def __init__(self, gateway, entry):
        self.gateway = gateway
        self.entry = entry
        self.name = entry["index"]
        self.namespace = entry.get("namespace", "hearth")
        self.base = f"indexes/{quote(self.name, safe='')}"
        self.records = f"records/namespaces/{quote(self.namespace, safe='')}"
        self.rerank_unavailable = False
        self.vector_transport = False

    def control(self, path, body=None):
        return retry(lambda: self.gateway.json(self.entry, path, body, timeout=8))

    def data(self, path, body, *, timeout=8):
        return self.gateway.json(self.entry, f"{self.base}/{path}", body, timeout=timeout)

    def bootstrap(self, dense_available):
        try:
            model = self.control(self.base)
        except ConnectorError as error:
            if error.status != 404 or error.missing_connection:
                raise
            self.create(dense_available)
            model = self.control(self.base)
        for delay in (0.5, 1, 2, 4, 6, 8):
            if (model.get("status") or {}).get("ready", True):
                break
            time.sleep(delay)
            model = self.control(self.base)
        else:
            if not (model.get("status") or {}).get("ready"):
                raise ConnectorError("Pinecone is still preparing the index. Hearth will retry.", 503)
        host, dimension = model.get("host"), model.get("dimension")
        if not isinstance(host, str) or not INDEX_HOST.fullmatch(host):
            raise ConnectorError("Pinecone did not return a valid index host.")
        if type(dimension) is not int or dimension < 1 or model.get("metric") != "cosine":
            raise ConnectorError("Hearth needs a dense Pinecone index with cosine similarity.")
        embed = model.get("embed") or {}
        if embed and (not isinstance(embed, dict) or (embed.get("field_map") or {}).get("text") != "text"):
            raise ConnectorError("The Pinecone index must map embedding input to the text field.")
        embedding_model = embed.get("model") or self.entry.get("embedding_model") or (
            "intfloat/multilingual-e5-base" if dimension == 768 else DENSE_MODEL)
        if not embed and not dense_available:
            raise ConnectorError("Connect Hugging Face to use this dense Pinecone index.")
        return {"host": host, "dimension": dimension, "embedding_model": embedding_model,
                "integrated": bool(embed)}

    def create(self, dense_available):
        cloud, region = self.entry.get("cloud", "aws"), self.entry.get("region", "us-east-1")
        try:
            self.control("indexes/create-for-model", {
                "name": self.name, "cloud": cloud, "region": region,
                "embed": {"model": self.entry.get("model", "multilingual-e5-large"),
                          "field_map": {"text": "text"}, "metric": "cosine",
                          "write_parameters": {"input_type": "passage", "truncate": "END"},
                          "read_parameters": {"input_type": "query", "truncate": "END"}},
            })
            return
        except ConnectorError as error:
            if error.status == 409:
                return
            if error.status not in BLOCKED:
                raise
            if not dense_available:
                raise ConnectorError(f"Integrated index creation returned HTTP {error.status}. "
                                     "Connect Hugging Face to try dense index creation.", error.status) from None
        try:
            self.control("indexes", {
                "name": self.name, "dimension": DENSE_DIMENSION, "metric": "cosine",
                "spec": {"serverless": {"cloud": cloud, "region": region}},
            })
        except ConnectorError as error:
            if error.status == 409:
                return
            if error.status in (401, 403, 404, 405, 501):
                raise ConnectorError(
                    f"Fly’s Pinecone gateway rejected index creation (HTTP {error.status}). "
                    f"Create {self.name} in Pinecone as a {DENSE_DIMENSION}-dimension cosine serverless index, "
                    "then sync again.", error.status, unsupported=error.unsupported) from None
            raise

    def stats(self):
        response = retry(lambda: self.data("describe_index_stats", {}))
        namespaces = response.get("namespaces")
        if not isinstance(namespaces, dict):
            raise ConnectorError("Pinecone did not return index statistics.")
        summary = namespaces.get(self.namespace, {})
        record_count = summary.get("vectorCount", 0) if isinstance(summary, dict) else None
        if type(record_count) is not int or record_count < 0:
            raise ConnectorError("Pinecone returned an invalid record count.")
        return record_count

    def list_ids(self):
        ids = set()
        query = {"namespace": self.namespace, "limit": 100}
        try:
            while True:
                response = retry(lambda: self.data(f"vectors/list?{urlencode(query)}", None))
                ids.update(row["id"] for row in response.get("vectors", [])
                           if isinstance(row, dict) and isinstance(row.get("id"), str))
                token = response.get("pagination", {}).get("next")
                if not token or token == query.get("paginationToken"):
                    return ids
                query["paginationToken"] = token
        except ConnectorError as error:
            if error.status in BLOCKED:
                return None
            raise

    def hosted_vectors(self, model, texts, kind, *, timeout=20):
        response = self.gateway.json(self.entry, "embed", {
            "model": model, "inputs": [{"text": text} for text in texts],
            "parameters": {"input_type": kind, "truncate": "END"},
        }, timeout=timeout)
        try:
            vectors = [row["values"] for row in response["data"]]
        except (KeyError, TypeError):
            raise ConnectorError("Pinecone returned an invalid embedding response.") from None
        if len(vectors) != len(texts) or any(not isinstance(vector, list) or not vector or
                not all(type(value) in (int, float) and math.isfinite(value) for value in vector) for vector in vectors):
            raise ConnectorError("Pinecone returned invalid embeddings.")
        return vectors

    def upsert(self, info, records, embed):
        if info["integrated"] and not self.vector_transport:
            body = "".join(json.dumps({"_id": row["memory_id"], **row}, ensure_ascii=False) + "\n"
                           for row in records).encode("utf-8")

            def request():
                with self.gateway.open(self.entry, f"{self.base}/{self.records}/upsert", body,
                                       {"Content-Type": "application/x-ndjson"}, timeout=12):
                    pass

            try:
                retry(request)
                return
            except ConnectorError as error:
                if error.status not in BLOCKED:
                    raise
                self.vector_transport = True
        if info["integrated"]:
            embed = self.hosted_vectors
        vectors = retry(lambda: embed(info["embedding_model"], [record["text"] for record in records], "passage"))
        if any(len(vector) != info["dimension"] for vector in vectors):
            raise ConnectorError(f"The embedding model must return {info['dimension']}-dimension vectors.")
        body = {"namespace": self.namespace, "vectors": [
            {"id": row["memory_id"], "values": vector, "metadata": row}
            for row, vector in zip(records, vectors, strict=True)]}
        retry(lambda: self.data("vectors/upsert", body, timeout=12))

    def delete(self, ids):
        retry(lambda: self.data("vectors/delete", {"namespace": self.namespace, "ids": ids}))

    def query(self, info, query, top_k, filters, embed, deadline):
        if info["integrated"] and not self.vector_transport:
            search = {"inputs": {"text": query}, "top_k": top_k}
            if filters:
                search["filter"] = filters
            try:
                response = self.data(f"{self.records}/search", {"query": search, "fields": ["text"]},
                                     timeout=remaining(deadline))
                return self.matches(response.get("result", {}).get("hits"), "_id", "_score")
            except ConnectorError as error:
                if error.status not in BLOCKED:
                    raise
                self.vector_transport = True
        if info["integrated"]:
            embed = self.hosted_vectors
        vector, = embed(info["embedding_model"], [query], "query", timeout=remaining(deadline))
        if len(vector) != info["dimension"]:
            raise ConnectorError("The query does not match the Pinecone index dimension.")
        body = {"namespace": self.namespace, "vector": vector, "topK": top_k}
        if filters:
            body["filter"] = filters
        response = self.data("query", body, timeout=remaining(deadline))
        return self.matches(response.get("matches"), "id", "score")

    @staticmethod
    def matches(rows, id_key, score_key):
        if not isinstance(rows, list):
            raise ConnectorError("Pinecone returned invalid search results.")
        return [(row[id_key], float(row[score_key])) for row in rows if isinstance(row, dict)
                and isinstance(row.get(id_key), str) and type(row.get(score_key)) in (int, float)
                and math.isfinite(row[score_key])]

    def rerank(self, query, hits, deadline):
        if self.rerank_unavailable or len(hits) < 2 or deadline - time.monotonic() < 0.08:
            return hits, False
        try:
            response = self.gateway.json(self.entry, "rerank", {
                "model": RERANK_MODEL, "query": query, "rank_fields": ["text"], "top_n": len(hits),
                "documents": [{"text": redact_text(hit["heading"] + "\n" + hit["excerpt"])[:1200]} for hit in hits],
            }, timeout=min(0.18, remaining(deadline)))
        except ConnectorError as error:
            if error.status in BLOCKED:
                self.rerank_unavailable = True
            return hits, False
        rows = response.get("data")
        if not isinstance(rows, list):
            return hits, False
        scores = {row["index"]: row["score"] for row in rows if isinstance(row, dict)
                  and type(row.get("index")) is int and 0 <= row["index"] < len(hits)
                  and type(row.get("score")) in (int, float) and math.isfinite(row["score"])}
        if len(scores) != len(hits):
            return hits, False
        return sorted(({**hit, "score": round(scores[i], 4)} for i, hit in enumerate(hits)),
                      key=lambda hit: -hit["score"]), True
