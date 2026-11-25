"""Model routing based on prompt features, model tags, and recent attempts."""

import json
import re
import time
from statistics import median

from . import file_intent
from .connectors import MODEL_PATHS
from .storage import HearthError, atomic_write

TURN_TYPES = {
    "quick": ("Quick chat", "Favors speed and lower cost"),
    "tool": ("Tool or action", "Favors reliable tool calling"),
    "reasoning": ("Long reasoning or planning", "Favors more context"),
    "planning": ("Planning", "Favors planning and tool capability"),
    "code": ("Code", "Favors coding models and more context"),
    "multilingual": ("Multilingual", "Favors multilingual models"),
    "vision": ("Image attachments", "Uses a model that accepts images"),
    "side": ("Side chat", "Favors speed and lower cost"),
}
TAG_OPTIONS = {
    "speed": ("slow", "balanced", "fast"),
    "cost": ("low", "medium", "high"),
    "tools": ("low", "medium", "high"),
}
DEFAULT_TAGS = {"speed": "balanced", "cost": "medium", "tools": "medium",
                "context": 32_768, "multilingual": False}
KIMI = "moonshotai/Kimi-K3.1-Pro:fastest"
FLASH = "deepseek-ai/DeepSeek-V4.1-Flash:fastest"
PRO = "deepseek-ai/DeepSeek-V4-Pro-0813:fastest"
QWEN = "Qwen/Qwen3-Coder-Next:fastest"
PREFERRED_MODELS = (KIMI, FLASH, PRO, QWEN)
VISION_MODELS = (KIMI, FLASH)
RETIRED_MODEL = "meta-llama/llama-3.1-8b-instruct"


def retired_model(model):
    return isinstance(model, str) and model.casefold().split(":")[0] == RETIRED_MODEL


SIDE_COMMAND = re.compile(r"^/(?:side|btw)(?:\s+|$)", re.I)
ACTION = re.compile(
    r"^\s*(?:search for|look up|check the weather)\b|"
    r"\b(?:remind\s+me|set\s+(?:an?\s+)?reminder|schedule\s+(?!a\s+plan)|"
    r"(?:draft|send|write)\b.{0,45}\b(?:email|invitation)|"
    r"(?:search|look up|browse)\s+(?:the\s+)?(?:web|internet|online)|"
    r"(?:open|show|close|switch to)\s+(?:the\s+)?(?:\w+\s+)?panel|"
    r"(?:find|list|search|check|look up|read|open|update|edit|write|wipe|delete|save)\b.{0,35}"
    r"(?:\b(?:my|the|our)\s+(?:notes?|memory|calendar|inbox)|\b[\w/-]+\.md\b)|"
    r"remember\s+(?:that|this)|gateway\s+\S+\s+(?:get|post|patch|put|delete)|"
    r"undo\s+(?:that|the|my)|checkpoint|plan thanksgiving dinner)\b|"
    r"提醒我|设置提醒|发送邮件|搜索网页|查看.{0,8}笔记", re.I,
)
CODE = re.compile(
    r"```|\b(?:code|coding|debug|refactor|stack trace|traceback|regex|"
    r"python|javascript|typescript|sql|rust|golang|bash)\b|"
    r"\b(?:write|fix|implement|review|test)\b.{0,35}\b(?:function|script|program|query|class|api)\b|"
    r"代码|编程|函数", re.I,
)
REASONING = re.compile(
    r"\b(?:step.by.step|trade.offs?|in depth|deep dive|"
    r"reason through|analy[sz]e|(?:compare|evaluate)\b.{0,60}\b(?:options|approaches|alternatives))\b", re.I,
)
LANGUAGE = re.compile(
    r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0400-\u052f\u0590-\u06ff\u0900-\u097f\u0e00-\u0e7f]"
    r"|[¿¡]|\b(?:bonjour|gracias|hola|merci|obrigad[oa]|bitte|danke)\b"
    r"|\b(?:in|into|to) (?:chinese|spanish|french|german|japanese|korean|arabic|hindi|russian|portuguese)\b",
    re.I,
)
REQUIRED_ACTIONS = (
    (re.compile(r"\b(?:remind me|set (?:an? )?reminder|schedule a reminder)\b|提醒我|设置提醒", re.I), {"schedule"}),
    (re.compile(r"\b(?:draft|send)\b.{0,45}\b(?:email|invitation)\b|发送邮件", re.I), {"send_email"}),
    (re.compile(r"\bremember\s+(?:that|this)\b|记住", re.I), {"remember_fact", "memory_write"}),
    (re.compile(r"\b(?:write|wipe|edit|update|delete|save|forget)\b.{0,40}(?:\b[\w/-]+\.md\b|\b(?:my|the) (?:notes?|memory)\b)", re.I), {"memory_write"}),
    (re.compile(r"^\s*(?:checkpoint|save a checkpoint)\b", re.I), {"checkpoint"}),
    (re.compile(r"^\s*undo\b", re.I), {"undo"}),
)
SMALL_MODEL = re.compile(r"(?:^|[-_/])(?:[1-9](?:\.\d+)?b|mini|nano|flash|lite|small|haiku)(?:$|[-_:])", re.I)
CODE_MODEL = re.compile(r"(?:^|[-_/])(?:coder|code|codestral|devstral)(?:$|[-_:])", re.I)
SAMPLE_LIMIT = 24
SAMPLE_AGE = 7 * 24 * 60 * 60
FAILURE_COOLDOWN = 5 * 60
MAX_POOL = 32


def classify(prompt, *, side=False, file_request=False, image_attachment=False):
    command = SIDE_COMMAND.match(prompt.strip())
    if command:
        side, prompt = True, prompt.strip()[command.end():]
    if image_attachment:
        return "vision"
    if file_request or file_intent.intent(prompt) or ACTION.search(prompt):
        return "tool"
    if CODE.search(prompt):
        return "code"
    if REASONING.search(prompt) or len(prompt) >= 800:
        return "reasoning"
    if LANGUAGE.search(prompt):
        return "multilingual"
    if re.search(r"\b(?:plan|roadmap|strategy)\b", prompt, re.I):
        return "planning"
    return "side" if side else "quick"


def model_key(model):
    return f"{model['provider']}:{model['model']}"


def model_tags(model, defaults):
    name = model["model"]
    tags = DEFAULT_TAGS.copy()
    if SMALL_MODEL.search(name):
        tags.update(speed="fast", cost="low")
    if re.search(r"qwen|gemma|gemini|mistral|muse", name, re.I):
        tags["multilingual"] = True
    return {**tags, **defaults.get(model_key(model), {}), **model.get("tags", {})}


def validate_tags(tags):
    if not isinstance(tags, dict) or tags.keys() - DEFAULT_TAGS.keys():
        raise HearthError("Invalid model tags.")
    for key, options in TAG_OPTIONS.items():
        if key in tags and tags[key] not in options:
            raise HearthError("Choose a listed speed, cost, or tool reliability tag.")
    if "context" in tags and (type(tags["context"]) is not int or not 1 <= tags["context"] <= 10_000_000):
        raise HearthError("Enter a context size between 1 and 10,000,000 tokens.")
    if "multilingual" in tags and type(tags["multilingual"]) is not bool:
        raise HearthError("Choose whether the model supports multiple languages.")
    return tags


def pool_models(models, pool, defaults):
    available = {entry["provider"]: entry for entry in models if entry["provider"] != "mock"}
    candidates = [
        {**available[row["provider"]], **row} for row in pool if row["provider"] in available
    ] if pool else default_models(available, defaults)
    return [{**entry, "tags": model_tags(entry, defaults)} for entry in candidates
            if not retired_model(entry["model"])]


def default_models(available, defaults):
    candidates = list(available.values())
    if (hf := available.get("huggingface")) and f"huggingface:{KIMI}" in defaults:
        candidates = [model for model in candidates if model["provider"] != "huggingface"]
        candidates.extend({**hf, "model": name} for name in PREFERRED_MODELS)
    return candidates


def mode_for(selection, pool):
    provider = selection["provider"]
    if provider == "auto":
        return "smart" if len(pool) >= 2 else "priority"
    return provider


def setup(config, selection=None, pool=None):
    if selection is None:
        selection = config.get("brain", {"provider": "auto", "model": ""})
    if pool is None:
        pool = config.get("brain_pool", [])
    defaults = config.get("brain_tags", {})
    connected = [item for item in config["llm"] if item["provider"] == "mock"
                 or item["provider"] in MODEL_PATHS and item["connection_id"]]
    models = [{**model, "tags": model_tags(model, defaults)} for model in connected]
    candidates = pool_models(connected, pool, defaults)
    mode = mode_for(selection, candidates)
    if mode == "smart":
        if not candidates:
            candidates = pool_models(connected, [], defaults)
        return mode, candidates + [model for model in models if model["provider"] == "mock"], None
    configured_keys = {model_key(item) for item in models}
    alternatives = [model for model in pool_models(connected, [], defaults)
                    if model_key(model) not in configured_keys]
    configured = [model for model in models if model["provider"] != "mock"]
    fallback = [*configured, *alternatives, *[model for model in models if model["provider"] == "mock"]]
    if mode == "priority":
        return mode, fallback, None
    chosen = next((model for model in models if model["provider"] == mode), None)
    if mode == "mock":
        return mode, [chosen], None
    if chosen:
        pinned = {**chosen, "model": selection["model"]}
        pinned["tags"] = model_tags({key: value for key, value in pinned.items() if key != "tags"}, defaults)
        return mode, [pinned, *[model for model in fallback if model_key(model) != model_key(pinned)]], None
    return mode, fallback, mode


def score(model, turn_type):
    tags = model.get("tags", DEFAULT_TAGS)
    speed = TAG_OPTIONS["speed"].index(tags["speed"])
    cost = TAG_OPTIONS["cost"].index(tags["cost"])
    tools = TAG_OPTIONS["tools"].index(tags["tools"])
    context = min(tags["context"] / 32_768, 8)
    if turn_type == "tool":
        return 9 * tools + context + speed
    if turn_type == "code":
        return 10 * bool(CODE_MODEL.search(model["model"])) + context + speed
    if turn_type == "reasoning":
        return 2 * context + tools
    if turn_type == "multilingual":
        return 10 * tags["multilingual"] + speed + context / 4
    return 4 * speed - 2 * cost


def order_models(models, turn_type, mode, stats, *, now=None):
    """Rank a copy of the smart pool. Mock stays at the end in every automatic mode."""
    if mode != "smart" and turn_type not in {"tool", "vision"}:
        reason = {"priority": "Provider priority", "mock": "Mock selected"}.get(mode, "Selected provider")
        return list(models), reason
    now = time.time() if now is None else now
    reason = TURN_TYPES[turn_type][1]
    eligible = [model for model in models if model["provider"] != "mock"]
    mock = [model for model in models if model["provider"] == "mock"]
    if turn_type == "tool":
        trusted = [model for model in eligible if model.get("tags", {}).get("tools") == "high"]
        if mode != "smart" and not trusted:
            return [model for model in eligible if model["provider"] != "huggingface"] + mock, reason
        eligible = trusted
    if turn_type == "vision":
        eligible = [model for model in eligible if model["model"] in VISION_MODELS]
    preferred = {
        "quick": FLASH, "side": FLASH, "tool": KIMI, "planning": KIMI,
        "multilingual": KIMI, "reasoning": PRO, "code": PRO, "vision": KIMI,
    }.get(turn_type)
    preference = list(dict.fromkeys((preferred, FLASH, KIMI, PRO, QWEN)))

    def rank(model, health):
        quality = score(model, turn_type)
        if model["provider"] == "huggingface" and model["model"] in preference:
            quality += (len(preference) - preference.index(model["model"])) * 30
        if not health:
            return False, -quality
        failed_at = health["last_failure"]
        recent = failed_at is not None and now - failed_at < FAILURE_COOLDOWN
        latency = health["p50_ms"] or 0
        latency_penalty = min(max(latency - 2_000, 0) / 1_000, 12)
        if turn_type not in ("quick", "side"):
            latency_penalty /= 2
        return recent, -(quality - latency_penalty - 8 * health["error_rate"])

    ordered = sorted(eligible, key=lambda model: rank(model, stats.get(model_key(model))))
    first_choice = min(eligible, key=lambda model: rank(model, None), default=None)
    if ordered and ordered[0] is not first_choice:
        recent, _ = rank(first_choice, stats.get(model_key(first_choice)))
        reason += "; avoided a recent failure" if recent else "; recent latency and errors considered"
    if not ordered:
        reason = "No connected model in the routing pool"
    return ordered + mock, reason


class BrainStats:
    def __init__(self, storage):
        self.storage = storage
        self.path = storage.root / "brain_stats.json"

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def snapshot(self, *, now=None):
        now = time.time() if now is None else now
        return {key: summary for key, data in self._load().items()
                if (summary := self._summary(data, now))["sample_count"]}

    @staticmethod
    def _recent(data, now):
        samples = data.get("recent") if isinstance(data, dict) else None
        if not isinstance(samples, list):
            return []
        return [sample for sample in samples[-SAMPLE_LIMIT:]
                if isinstance(sample, dict) and type(sample.get("at")) in (int, float)
                and now - SAMPLE_AGE <= sample["at"] <= now
                and type(sample.get("ms")) is int and sample["ms"] >= 0
                and type(sample.get("ok")) is bool]

    @classmethod
    def _summary(cls, data, now):
        recent = cls._recent(data, now)
        successful = [sample["ms"] for sample in recent if sample["ok"]]
        failures = [sample["at"] for sample in recent if not sample["ok"]]
        return {"p50_ms": round(median(successful)) if successful else None,
                "error_rate": len(failures) / len(recent) if recent else 0,
                "last_failure": max(failures, default=None), "sample_count": len(recent)}

    def record(self, model, ok, latency_ms, *, now=None):
        if model["provider"] == "mock":
            return
        now = time.time() if now is None else now
        key = model_key(model)
        with self.storage.lock():
            data = self._load()
            data = {name: row for name, row in data.items()
                    if self._summary(row, now)["sample_count"]}
            recent = self._recent(data.get(key), now)
            recent.append({"at": now, "ms": latency_ms, "ok": ok})
            row = {"recent": recent[-SAMPLE_LIMIT:]}
            data[key] = {**row, **self._summary(row, now)}
            atomic_write(self.path, json.dumps(data) + "\n")
