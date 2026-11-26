"""Policy and persisted approval decisions for brain tools."""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from . import browserbase, memory, timeline
from .connections import catalog_entry
from .connectors import ConnectorError
from .gateway_tools import scrub, validate_request
from .storage import HearthError, atomic_write, iso, new_id
from .threads import MAIN

CONNECTOR_CATEGORIES = ("send", "spend", "public", "destructive")
CATEGORIES = (*CONNECTOR_CATEGORIES, "skills", "goals")
DEFAULTS = dict.fromkeys(CATEGORIES, "ask")
LABELS = {"send": "Send", "spend": "Spend", "public": "Publish", "destructive": "Delete", "skills": "Skills",
          "goals": "Create goals"}
READ_TOOLS = frozenset({
    "memory_read", "memory_search", "web_search", "read_artifact", "ask_files", "list_reminders", "list_recurring_tasks",
    "browse_fetch", "browse_search", "undo", "skill_load",
})
LOCAL_TOOLS = frozenset({
    "remember_fact", "schedule", "checkpoint", "create_panel", "update_panel", "create_recurring_task",
    "update_recurring_task", "pause_recurring_task", "create_document", "create_pdf", "create_spreadsheet",
    "create_presentation", "update_document", "update_pdf", "update_spreadsheet", "update_presentation",
    "spawn_workers", "memory_move", "create_event_automation",
})
DELETE_TOOLS = frozenset({"delete_panel", "delete_recurring_task", "delete_event_automation", "delete_memory", "delete_artifact", "memory_forget"})
SAFE_HTTP = {"GET", "HEAD", "OPTIONS"}


def policy(state):
    return {**DEFAULTS, **state.get("approval_policy", {})}


def settings(storage, changes):
    if not changes.keys() <= DEFAULTS.keys() or any(value not in ("ask", "allow") for value in changes.values()):
        raise HearthError("Choose Always ask or Allow without asking for each approval category.")
    with storage.lock():
        state = storage.load()
        state["approval_policy"] = {**policy(state), **changes}
        path = memory.APPROVAL_NOTE
        previous = storage.read(path) if storage.memory_path(path).is_file() else None
        try:
            storage.write(path, memory.approval_content(state["approval_policy"], previous))
            memory.catalog(storage)
            storage.save(state)
        except OSError:
            if previous is None:
                storage.memory_path(path).unlink(missing_ok=True)
            else:
                storage.write(path, previous)
            memory.catalog(storage)
            raise
        return state["approval_policy"]


def connector_effects(provider, method, path, body):
    route = unquote(path.split("?", 1)[0]).casefold()
    payload = json.dumps(body or {}, ensure_ascii=False).casefold()
    effects = set()
    paid = catalog_entry(provider).get("paid_api_calls", ())
    if any(rule["method"] == method and re.search(rule["path"], route) for rule in paid):
        effects.add("spend")
    if method in SAFE_HTTP:
        return effects
    if method == "DELETE":
        return effects | {"destructive"} if provider == "box" else set(CONNECTOR_CATEGORIES)
    if effects and provider in {"browserbase", "fireworks", "openai", "anthropic", "openrouter", "nebius_jobs", "apify"}:
        return effects
    # The raw gateway cannot infer the behavior of an arbitrary endpoint or a
    # structured query. Only known routes get a narrower classification.
    if provider == "agentmail" and re.search(r"/(?:send|reply|reply-all)$", route):
        return effects | {"send"}
    if provider == "box" and ("/shared_link" in route or "shared_link" in payload or "collaborations" in route):
        return effects | {"send", "public"}
    if provider in {"slack", "slack_bot"} and re.search(r"(?:chat\.postmessage|chat\.schedulemessage)$", route):
        return effects | {"send", "public"}
    if provider in {"resend", "pushover"} and re.search(r"(?:emails|messages\.json)$", route):
        return effects | {"send"}
    if provider in {"discourse", "blotato", "github"} and re.search(r"(?:posts|comments|issues|pulls)$", route):
        return effects | {"public", "send"}
    return set(CONNECTOR_CATEGORIES)


def classify(tool, args, *, prompt=""):
    if tool == "goal_create":
        return ("goals",)
    if tool == "goal_update" and args.get("delete") is True:
        return ("destructive",)
    if tool in {"goal_update", "goal_checkin"}:
        return ()
    if tool in READ_TOOLS or tool in LOCAL_TOOLS:
        return ()
    if tool in DELETE_TOOLS:
        return ("destructive",)
    if tool in {"skill_create", "skill_edit"}:
        return ("skills",)
    if tool in {"send_email", "email_acknowledgment"}:
        return ("send",)
    if tool == "browse_session":
        steps = browserbase.normalize_steps(args.get("steps"))
        # Interacting with a page may submit, publish, or remove data.
        return CONNECTOR_CATEGORIES if any(step["action"] in browserbase.WRITE_STEPS for step in steps) else ("spend",)
    if tool in {"memory_write", "memory_edit"}:
        notes = args.get("notes")
        clears = isinstance(notes, list) and any(isinstance(note, dict) and isinstance(note.get("content"), str)
                                                 and not note["content"].strip() for note in notes)
        return ("destructive",) if clears or re.search(r"\b(?:wipe|clear|blank|erase|remove|delete|forget)\b|删除|清空", prompt, re.I) else ()
    if tool == "gateway_request":
        provider = args.get("provider")
        if not isinstance(provider, str):
            raise HearthError("Choose a connected provider.")
        method, path = validate_request(provider, args.get("method"), args.get("path"), args.get("body"))
        return tuple(category for category in CATEGORIES
                     if category in connector_effects(provider, method, path, args.get("body")))
    raise HearthError("This tool has no approval policy.")


def needs_approval(state, categories, *, scheduled=False):
    return bool(categories) and (scheduled or any(policy(state)[item] == "ask" for item in categories))


def log(state, row, decision, now):
    state.setdefault("activity", []).append(timeline.entry(
        "approval", f"{decision} · {row['title']}", row, id=new_id(), at=iso(now),
        error=decision in {"Failed", "Outcome unconfirmed"}, data={
            "approval_id": row["id"], "status": row["status"], "categories": row["categories"],
        }))


def expire(state, now):
    changed = False
    for row in state["actions"].values():
        if row.get("tool") and row["status"] == "pending" and datetime.fromisoformat(row["expires_at"]) <= now:
            row.update(status="expired", updated_at=iso(now))
            log(state, row, "Expired", now)
            changed = True
    return changed


def upgrade_legacy(agent):
    """Keep existing pending side-effect cards under the current policy and expiry."""
    storage = agent.storage
    with storage.lock():
        state = storage.load()
        changed = False
        for row in state["actions"].values():
            if row["status"] != "pending" or row.get("tool"):
                continue
            kind = row["kind"]
            if kind == "email":
                tool, args = "send_email", row["email"]
                _, fields = agent.prepare_approval(tool, args)
                fields["mocked"] = row["mocked"]
            elif kind == "gateway":
                tool, args = "gateway_request", row["request"]
                fields = {"binding": row["target"], "target": f"{args['provider']} {args['path']}",
                          "amount": "Provider rates apply. Exact cost unavailable.",
                          "editable": {"body": json.dumps(args.get("body"), ensure_ascii=False, indent=2)}}
            elif kind == "browse":
                tool, args = "browse_session", {key: row[key] for key in ("url", "steps")}
                fields = {"target": row["url"], "amount": f"Up to {browserbase.SESSION_SECONDS} seconds at your plan rate.",
                          "editable": {}}
            else:
                continue
            created = datetime.fromisoformat(row["at"])
            row.update(fields, tool=tool, args=args, categories=list(classify(tool, args)),
                       created_at=row["at"], expires_at=iso(created + timedelta(hours=24)))
            changed = True
        if changed:
            expire(state, datetime.now(timezone.utc))
            storage.save(state)


def records(storage, *, pending=False, clock=None):
    with storage.lock():
        state = storage.load()
        if expire(state, clock or datetime.now(timezone.utc)):
            storage.save(state)
        return [row for row in reversed(state["actions"].values()) if row.get("tool") and (
            row["status"] == "pending" if pending else row["status"] in {"pending", "expired"}
        )]


def proposal(state, tool, args, categories, origin, fields, *, now=None, dedupe=None):
    now = now or datetime.now(timezone.utc)
    expire(state, now)
    if dedupe:
        existing = next((row for row in state["actions"].values() if row.get("dedupe") == dedupe), None)
        if existing:
            return existing
    row = {"id": new_id(), "kind": "approval", "status": "pending", "tool": tool,
           "args": args, "categories": list(categories), "at": iso(now), "created_at": iso(now),
           "expires_at": iso(now + timedelta(hours=24)), **origin, **fields}
    if dedupe:
        row["dedupe"] = dedupe
    state["actions"][row["id"]] = row
    return row


def receipt_path(storage, identity):
    return storage.root / "approval-receipts" / f"{identity}.json"


def decide(agent, identity, operation, changes=None, *, clock=None):
    now = clock or datetime.now(timezone.utc)
    storage = agent.storage
    with storage.lock():
        state = storage.load()
        if expire(state, now):
            storage.save(state)
        row = state["actions"].get(identity)
        if not row or not row.get("tool"):
            raise HearthError("This approval does not exist.")
        if row["status"] != "pending":
            return row
        if operation == "edit":
            agent.edit_approval(row, changes)
            log(state, row, "Edited", now)
        elif operation == "decline":
            row.update(status="declined", result={"message": "The user declined this action. It did not run."})
            log(state, row, "Declined", now)
        elif operation in {"approve", "allow"}:
            if (path := receipt_path(storage, identity)).is_file():
                return {**row, "status": "changing", "result": {"message": "There is already an execution attempt."}}
            row["status"] = "changing"
            row["decision"] = operation
            atomic_write(path, iso(now))
            log(state, row, "Approved" if operation == "approve" else "Allowed by policy", now)
        else:
            raise HearthError("Choose Approve, Edit, or Decline.")
        row["updated_at"] = iso(now)
        storage.save(state)
        if operation == "decline":
            append_result(agent, row)
    if operation in {"approve", "allow"}:
        try:
            status, result = agent.execute_approved(row)
        except ConnectorError as error:
            definite = error.status and 400 <= error.status < 500 and error.status not in {408, 409, 429}
            status, result = ("failed" if definite else "request_unknown"), {"error": str(error)}
        except HearthError as error:
            status, result = "failed", {"error": str(error)}
        except Exception:
            status, result = "request_unknown", {"error": "Hearth could not confirm the action’s outcome."}
        with storage.lock():
            state = storage.load()
            row.update(status=status, result=scrub(result), updated_at=iso(clock))
            state["actions"][identity] = row
            log(state, row, {"request_unknown": "Outcome unconfirmed", "unknown": "Outcome unconfirmed",
                             "failed": "Failed", "partial": "Partially applied", "simulated": "Simulated"}.get(status, "Completed"),
                clock or datetime.now(timezone.utc))
            storage.save(state)
            if operation == "approve":
                append_result(agent, row)
    return row


def append_result(agent, row):
    worker = agent.storage.load().get("workers", {}).get(row.get("worker_id"))
    if worker and worker["status"] in {"queued", "running", "waiting_approval"}:
        return
    thread = row.get("thread_id", MAIN)
    if thread not in agent.threads.load_index():
        return
    result = row["result"]
    content = result.get("message") or result.get("error")
    if not content:
        content = "Hearth recorded the tool result on the approval card."
    agent.threads.append(thread, "assistant", content, source="approval", approval_id=row["id"],
                         **({"browse_images": result["browse_images"]} if result.get("browse_images") else {}))
