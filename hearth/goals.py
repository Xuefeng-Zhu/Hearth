"""Structured goal memory, check-in scheduling, and scoped Timeline undo."""

from copy import deepcopy
from datetime import date, datetime, timezone
import re
from uuid import NAMESPACE_URL, uuid5

from . import memory, reminders, scheduler
from .panels import text
from .reminder_config import saved
from .storage import HearthError, iso, new_id
from .threads import MAIN_ORIGIN

FIELDS = {"title", "target_date", "links", "checkin"}
TOOLS = {"goal_create", "goal_update", "goal_checkin"}
DIRECT = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you)\s+)*"
    r"(?:(?:create|add|track|set|start|update|edit|rename|delete|remove|complete|link|unlink|"
    r"mark|log|record|change|move|finish|close|check[ -]?in|help me track)\b[^\n]{0,180}"
    r"\b(?:goals?|progress|check[ -]?in|milestone|target|it|this|that)\b"
    r"|(?:my (?:new )?goal|goal)\s*(?:is|:)"
    r"|i (?:want|aim|plan|intend) to\b[^\n]{0,160}(?:\btrack\b|\b\d+\s*(?:times|x)\s*(?:a|per) week)"
    r"|i (?:reached|finished|completed|made)\b[^\n]{0,160}\b(?:goals?|progress|milestone|target)\b)", re.I,
)


def require(state, identity):
    row = state.get("goal_memory", {}).get(identity) if isinstance(identity, str) else None
    if not row or row.get("deleted"):
        raise HearthError("Choose an existing goal.")
    return row


def private_field(storage, value, limit):
    result = text(value, limit)
    memory.check_standing_rules(storage, result)
    return result


def link_options(state):
    return [
        {"id": row["id"], "kind": "reminder", "title": row["message"]}
        for row in reversed(state["jobs"])
        if row["status"] != "canceled" and not row.get("goal_id") and not row.get("root_job_id")
    ] + [
        {"id": row["id"], "kind": "task", "title": row["name"]}
        for row in state.get("recurring_tasks", {}).values() if not row.get("deleted")
    ]


def clean(storage, state, changes, before=None):
    if changes.keys() - FIELDS or (before and not changes):
        raise HearthError("Choose fields to update.")
    row = {"target_date": None, "links": [], "checkin": None, **(before or {}), **changes}
    row["title"] = private_field(storage, row.get("title"), 120)
    if (target := row["target_date"]) is not None:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target):
                raise ValueError
            row["target_date"] = date.fromisoformat(target).isoformat()
        except (TypeError, ValueError):
            raise HearthError("Enter a target date in YYYY-MM-DD format.") from None
    if "links" in changes:
        options = {(row["kind"], row["id"]) for row in link_options(state) + (before or {}).get("links", [])}
        links = row["links"]
        if not isinstance(links, list) or len(links) > 20:
            raise HearthError("Choose up to 20 linked reminders or tasks.")
        seen = set()
        for link in links:
            if (not isinstance(link, dict) or link.keys() != {"kind", "id"}
                    or not all(isinstance(value, str) for value in link.values())
                    or (key := (link["kind"], link["id"])) not in options or key in seen):
                raise HearthError("Choose distinct existing reminders or tasks.")
            seen.add(key)
    if (checkin := row["checkin"]) is not None:
        if not isinstance(checkin, dict) or checkin.keys() - {"cadence", "time", "day"}:
            raise HearthError("Choose a daily or weekly check-in.")
        cadence, at, day = checkin.get("cadence"), checkin.get("time"), checkin.get("day", 1)
        if (cadence not in ("daily", "weekly") or not isinstance(at, str)
                or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", at)
                or type(day) is not int or not 0 <= day <= 6):
            raise HearthError("Choose a daily or weekly check-in time and day.")
        row["checkin"] = {"cadence": cadence, "time": at, **({"day": day} if cadence == "weekly" else {})}
    return {key: row[key] for key in FIELDS}


def progress(state, row):
    total = len(row["links"])
    if not total:
        return {"mode": "manual", "percent": row["manual_progress"]}
    completed = {("reminder", item.get("root_job_id", item["job_id"])) for item in state["reminders"]
                 if not item.get("test") and (item.get("action") or {}).get("label") == "Done"}
    completed.update(("task", item["task_id"]) for item in state.get("task_runs", {}).values()
                     if item["status"] == "complete")
    count = sum((link["kind"], link["id"]) in completed for link in row["links"])
    return {"mode": "linked", "percent": round(100 * count / total), "completed": count, "total": total}


def suggestion_key(row, status):
    return [row["revision"], status["percent"]]


def public(state, row):
    status = progress(state, row)
    next_step = state.get("goal_steps", {}).get(row["id"], {})
    job = next((job for job in state["jobs"] if job.get("goal_id") == row["id"] and job.get("cron") and job["status"] == "scheduled"), {})
    return {**{key: row[key] for key in ("id", "revision", "manual_progress", "last_checkin", *FIELDS)},
            "progress": status, "next_checkin": job.get("next_fire_at") if status["percent"] < 100 else None,
            "next_step": next_step.get("text") if next_step.get("key") == suggestion_key(row, status) else None}


def list_goals(state):
    return [public(state, row) for row in reversed(list(state.get("goal_memory", {}).values()))
            if not row.get("deleted")]


def references(state):
    return {"goals": list_goals(state)[:30], "link_options": link_options(state)[:40],
            "timezone": saved(state)["timezone"]}


def sync_job(state, row, now, origin):
    active = next((job for job in state["jobs"] if job.get("goal_id") == row["id"]
                   and job.get("cron") and job["status"] == "scheduled"), None)
    checkin = row.get("checkin") if not row.get("deleted") and progress(state, row)["percent"] < 100 else None
    zone = saved(state)["timezone"]
    if active and checkin == active.get("goal_checkin") and row["title"] == active.get("goal_title") and zone == active.get("timezone"):
        return
    for job in state["jobs"]:
        if job.get("goal_id") == row["id"] and job["status"] == "scheduled":
            reminders.cancel(state, job["id"], now)
    if checkin:
        hour, minute = map(int, checkin["time"].split(":"))
        day = "*" if checkin["cadence"] == "daily" else checkin["day"]
        scheduler.add_job(state, f"Goal check-in · {row['title']}", now,
                          cron=f"{minute} {hour} * * {day}", timezone_name=zone, channel="app",
                          origin={**origin, "source": "goal", "goal_id": row["id"],
                                  "goal_checkin": checkin, "goal_title": row["title"]})


def reschedule_timezone(state, now):
    for row in list(state.get("goal_memory", {}).values()):
        job = next((job for job in state["jobs"] if job.get("goal_id") == row["id"]
                    and job.get("cron") and job["status"] == "scheduled"), None)
        if job:
            sync_job(state, row, now, action_origin(job))


def complete_linked(state, kind, identity, now):
    for row in state.get("goal_memory", {}).values():
        if (not row.get("deleted") and row["checkin"] and {"kind": kind, "id": identity} in row["links"]
                and progress(state, row)["percent"] == 100):
            sync_job(state, row, now, MAIN_ORIGIN)


def goal_job_due(state, job):
    row = state.get("goal_memory", {}).get(job["goal_id"])
    return bool(row and not row.get("deleted") and progress(state, row)["percent"] < 100
                and row.get("checkin") == job.get("goal_checkin"))


def prepare(storage, name, args):
    with storage.lock():
        state = storage.load()
        if name == "goal_create":
            changes = clean(storage, state, args)
            title = changes["title"]
            fields = {"target": title, "goal_preview": changes}
            return changes, {"title": f"Create goal · {title}", "editable": {}, **fields}
        if args.keys() - {"id", "delete", "revision"} or args.get("delete") is not True:
            raise HearthError("Choose a goal to delete.")
        row = require(state, args.get("id"))
        check_revision(row, args.get("revision"))
        return {"id": row["id"], "revision": row["revision"], "delete": True}, {
            "title": f"Delete goal · {row['title']}", "target": row["title"], "editable": {},
        }


def check_revision(row, revision):
    if revision is not None and row["revision"] != revision:
        raise HearthError("This goal changed. Refresh it and try again.")


def mutate(storage, name, args, *, origin=None, identity=None, clock=None):
    now = clock or datetime.now(timezone.utc)
    origin = origin or MAIN_ORIGIN
    args = args.copy()
    if name not in TOOLS:
        raise HearthError("Choose a goal action.")
    action_id = uuid5(NAMESPACE_URL, f"hearth:goal:{identity}").hex if identity else new_id()
    with storage.lock():
        state = storage.load()
        if action := state["actions"].get(action_id):
            row = state.get("goal_memory", {}).get(action["goal_change"])
            return {"action": action, "goal": public(state, row) if row and not row.get("deleted") else None}
        stored = state.setdefault("goal_memory", {})
        before = None if name == "goal_create" else require(state, args.pop("id", None))
        if before:
            check_revision(before, args.pop("revision", None))
        if name == "goal_create":
            row = {"id": identity or new_id(), "manual_progress": 0, "last_checkin": None,
                   **clean(storage, state, args)}
            verb = "Created goal"
        elif name == "goal_update":
            delete = args.pop("delete", False)
            if type(delete) is not bool:
                raise HearthError("Choose whether to delete the goal.")
            if delete:
                if args:
                    raise HearthError("Choose a goal to delete.")
                row, verb = {**before, "deleted": True}, "Deleted goal"
            else:
                row, verb = {**before, **clean(storage, state, args, before)}, "Updated goal"
        else:
            note = args.get("note", "")
            percent = args.get("progress")
            if (args.keys() - {"note", "progress"} or not isinstance(note, str)
                    or (percent is not None and (type(percent) is not int or not 0 <= percent <= 100))
                    or (percent is None and not note.strip())):
                raise HearthError("Enter a progress percentage from 0 to 100 or a check-in note.")
            if percent is not None and before["links"]:
                raise HearthError("This goal gets its progress from linked items. Record a note, or unlink them for manual progress.")
            row = {**before, "last_checkin": {"at": iso(now), "note": private_field(storage, note, 500) if note.strip() else ""}}
            if percent is not None:
                row["manual_progress"] = percent
            verb = "Checked in"
        row["revision"] = new_id()
        sync_job(state, row, now, origin)
        stored[row["id"]] = row
        action = {"id": action_id, "kind": "goal", "title": f"{verb} · {row['title']}", "status": "complete",
                  "at": iso(now), **origin, "goal_change": row["id"]}
        state["actions"][action["id"]] = action
        state.setdefault("goal_undo", {})[action["id"]] = {"before": before, "after": row["revision"]}
        storage.save(state)
        return {"action": action, "goal": None if row.get("deleted") else public(state, row)}


def can_undo(state, action):
    change = state.get("goal_undo", {}).get(action["id"])
    row = state.get("goal_memory", {}).get(action.get("goal_change"), {})
    return bool(change and not action.get("undone") and row.get("revision") == change["after"])


def undo(storage, identity, *, clock=None):
    now = clock or datetime.now(timezone.utc)
    with storage.lock():
        state = storage.load()
        action = state["actions"].get(identity)
        if not action or not can_undo(state, action):
            raise HearthError("This goal changed again. Undo the newer change first.")
        goal_id = action["goal_change"]
        stored = state["goal_memory"]
        before = deepcopy(state["goal_undo"][identity]["before"])
        if before:
            memory.check_standing_rules(storage, before["title"] + "\n" + (before.get("last_checkin") or {}).get("note", ""))
        sync_job(state, before or {**stored[goal_id], "deleted": True}, now, action_origin(action))
        if before:
            stored[goal_id] = before
        else:
            stored.pop(goal_id)
        action.update(undone=True, undone_at=iso(now))
        storage.save(state)
        return action


def action_origin(action):
    return {key: action[key] for key in ("thread_id", "thread_title", "source") if key in action}
