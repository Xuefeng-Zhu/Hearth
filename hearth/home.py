"""Build the Home snapshot and cache the Open-Meteo forecast."""
import json
import math
import threading
from datetime import datetime, time, timedelta, timezone
from enum import IntEnum
from heapq import nlargest
from http.client import HTTPException
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from . import approvals, panels, scheduler, timeline
from .artifacts import page_artifacts
from .connections import HEALTH_TTL
from .gateway_tools import redact_text, scrub
from .reminder_config import quiet_until, saved
from .storage import HearthError, iso, new_id, revision
from .threads import MAIN, compact

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_LOCATION = "Redmond, WA"
DEFAULT_PLACE = {"name": DEFAULT_LOCATION, "latitude": 47.674, "longitude": -122.1215}
WEATHER_MINUTES = 30
WEATHER_RETRY_MINUTES = 5
ACTIVITY_SIZE = 5
TITLES = {
    "today": "Today", "inbox": "Inbox to review", "weather": "Weather & clock", "files": "Recent files",
    "memory": "Memory", "activity": "Activity", "connections": "Connections health",
}


class ActivitySource(IntEnum):
    EVENT = 0
    CHAT = 1
    WORKER = 2
    AUTOMATION = 3
    ACTION = 4
    SCHEDULE = 5
    ROUTING = 6
    DELIVERY = 7
    CHECKPOINT = 8


def weather_state(state):
    return {"location": DEFAULT_LOCATION, "place": DEFAULT_PLACE, "value": None,
            "updated_at": None, "attempted_at": None, "error": None, "revision": "", **state.get("weather", {})}


def recent_artifacts(state):
    excluded = set(state.get("home_excluded_artifacts", []))
    files = [item for item in state.get("artifacts", {}).values() if not item.get("deleted")]
    files.extend(page_artifacts(state))
    files.sort(key=lambda item: item.get("updated_at") or item["created_at"], reverse=True)
    recent = {}
    for item in files:
        if item["id"] not in excluded:
            recent.setdefault(item["id"], {key: item[key] for key in ("id", "title", "format", "kind")})
        if len(recent) == 4:
            break
    return list(recent.values())


def chat_activity(messages, logged_recall):
    """Project Timeline's chat turns using only the fields shown on Home."""
    pending = None
    for row in messages:
        at, role = row.get("at"), row["role"]
        if role == "call":
            yield at, ActivitySource.CHAT, "voice", row["content"]
        elif role == "user":
            if pending:
                yield pending.get("at"), ActivitySource.CHAT, "chat", pending
            pending = row
            if row.get("shared_from"):
                yield at, ActivitySource.CHAT, "chat", "Shared a message to Main"
                pending = None
        elif role == "assistant":
            at = at or (pending and pending.get("at"))
            yield at, ActivitySource.CHAT, "chat", pending or "Hearth replied"
            if row.get("remembered") and (pending or row).get("id") not in logged_recall:
                yield at, ActivitySource.CHAT, "recall", "Memory recalled"
            pending = None
    if pending:
        yield pending.get("at"), ActivitySource.CHAT, "chat", pending


def activity_key(item):
    return datetime.fromisoformat(item[0]), -item[1]


def activity_title(title):
    if isinstance(title, dict):
        return compact(redact_text(title["content"]), 180) or "Chat message"
    return title


def activity_candidates(state, checkpoints):
    activity = state.get("activity", [])
    actions = state["actions"].values()
    represented_jobs = {row["job"]["id"] for row in actions if row.get("job")}
    represented_jobs.update(row["data"]["job"]["id"] for row in activity if row.get("data", {}).get("job"))
    represented_checkpoints = {row["checkpoint"]["id"] for row in actions if row.get("checkpoint")}
    for row in activity:
        yield row.get("at"), ActivitySource.EVENT, row
    for row in state.get("workers", {}).values():
        yield row.get("finished_at") or row.get("started_at") or row["queued_at"], ActivitySource.WORKER, row
    for row in state.get("event_runs", {}).values():
        yield row.get("finished_at", row["at"]), ActivitySource.AUTOMATION, row
    for row in actions:
        yield row.get("updated_at", row["at"]), ActivitySource.ACTION, row
    for row in state["jobs"]:
        if row["status"] == "scheduled" and row["id"] not in represented_jobs:
            yield row.get("created_at"), ActivitySource.SCHEDULE, row
    for row in state.get("routing", []):
        yield row["at"], ActivitySource.ROUTING, row
    for row in scheduler.email_records(state):
        yield row["delivered_at"], ActivitySource.DELIVERY, row
    for row in checkpoints:
        if row["id"] not in represented_checkpoints:
            yield row["created_at"], ActivitySource.CHECKPOINT, row


def activity_preview(group, row, state):
    if group == ActivitySource.EVENT:
        preview = {"data": {}, **row}
        if preview["kind"] == "inbox" and preview["title"].startswith("Email accepted · "):
            card = state.get("inbox", {}).get(preview["data"].get("inbox_id"))
            if card:
                preview["undone"] = card["status"] == "undone"
        return preview
    if group == ActivitySource.WORKER:
        return {"kind": "worker", "title": row["title"], "error": row["status"] == "failed"}
    if group == ActivitySource.AUTOMATION:
        status = row["status"]
        labels = {"approval_needed": "Needs approval", "complete": "Completed", "rate_limited": "Hourly limit reached",
                  "cancelled": "Stopped", "request_unknown": "Outcome unconfirmed", "partial": "Partially applied"}
        return {"kind": "automation", "title": f"{row['name']} · {labels.get(status, status.replace('_', ' ').capitalize())}",
                "error": status in {"failed", "request_unknown", "rate_limited", "partial"}}
    if group == ActivitySource.ACTION:
        return timeline.action_entry(row, lambda _: False)
    if group == ActivitySource.SCHEDULE:
        return {"kind": "reminder", "title": f"Reminder scheduled · {row['message']}"}
    if group == ActivitySource.ROUTING:
        first = next(iter(row["order"]), {})
        return {"kind": "routing", "title": f"Routed to {first.get('name', 'a model')} · {row['label']}"}
    if group == ActivitySource.DELIVERY:
        labels = {"app": "In app", "email": "Email"}
        delivery = row.get("delivery", {"app": {"status": "sent"}})
        status = " · ".join(f"{labels.get(channel, channel)} {info['status']}" for channel, info in delivery.items())
        late = f" · Late by {row['late_minutes']}m" if row.get("late_minutes") else ""
        title = "Reminder delivered" if delivery.get("app", {}).get("status") == "sent" else "Reminder"
        return {"kind": "reminder", "title": f"{title} · {row['message']} · {status}{late}",
                "error": any(info["status"] == "failed" for info in delivery.values())}
    return {"kind": "checkpoint", "title": row["comment"]}


def recent_activity(state, checkpoints, pinecone, mail_connected, since, until):
    candidates = list(activity_candidates(state, checkpoints))
    latest = {}
    for _, group, row in candidates:
        if group == ActivitySource.EVENT:
            if timeline.pinecone_sync({"data": {}, **row}, pinecone):
                latest["sync"] = row
            elif row["kind"] == "inbox" and row["title"] == "AgentMail inbox poll failed":
                latest["poll"] = row
    count = errors = 0
    items = []
    for at, group, row in sorted((item for item in candidates if item[0]), key=activity_key, reverse=True):
        parsed = datetime.fromisoformat(at)
        if parsed < since and len(items) == ACTIVITY_SIZE:
            break
        preview = activity_preview(group, row, state)
        if group in {ActivitySource.EVENT, ActivitySource.ACTION}:
            # Include the current incident records when classifying historical errors.
            context = [preview, *({"data": {}, **item} for item in latest.values() if item is not row)]
            timeline.actionable(context, state, pinecone, mail_connected)
        elif preview.get("error") and group == ActivitySource.AUTOMATION and row.get("undo_at"):
            from .event_automations import undoable
            if not undoable(state, row):
                continue
        if preview.get("diagnostic"):
            continue
        if since <= parsed < until:
            count += 1
            errors += bool(preview.get("error"))
        if len(items) < ACTIVITY_SIZE:
            items.append((at, group, preview["kind"], preview["title"]))
    return count, errors, items


def open_meteo(host, path, parameters):
    with urlopen(f"https://{host}.open-meteo.com/v1/{path}?{urlencode(parameters)}", timeout=7) as response:
        return json.loads(response.read(96 * 1024))


def weather_value(row):
    place = row["place"]
    if not place:
        matches = open_meteo("geocoding-api", "search", {"name": row["location"], "count": 1, "language": "en"})
        if not matches.get("results"):
            raise HearthError("Open-Meteo couldn’t find this location. Try a city and state or country.")
        result = matches["results"][0]
        place = {"name": ", ".join(dict.fromkeys(result[key] for key in ("name", "admin1", "country")
                                                   if result.get(key))),
                 "latitude": result["latitude"], "longitude": result["longitude"]}
    forecast = open_meteo("api", "forecast", {
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": str(PACIFIC),
        "current": "temperature_2m,weather_code", "temperature_unit": "fahrenheit", "forecast_days": 1,
    })["current"]
    temperature, code = forecast["temperature_2m"], forecast["weather_code"]
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or type(code) is not int:
        raise HearthError("Open-Meteo returned incomplete current conditions.")
    return place, {"temperature": round(temperature), "code": code}


def weather_label(code):
    if 0 <= code <= 3:
        return ("Clear", "Mostly clear", "Partly cloudy", "Overcast")[code]
    if code in (85, 86) or 71 <= code <= 77:
        return "Snow"
    return next(label for upper, label in (
        (48, "Fog"), (57, "Drizzle"), (67, "Rain"), (82, "Rain showers"), (99, "Thunderstorms"),
        (float("inf"), "Unknown conditions"),
    ) if code <= upper)


class Home:
    def __init__(self, app):
        self.app = app
        self.storage = app.storage
        self.panels = panels.Refreshes(app)
        self.weather_lock = threading.Lock()
        self.worker_lock = threading.Lock()
        self.activity_lock = threading.Lock()
        self.chat_activity_cache = {}
        self.checkpoint_activity_cache = None

    def signature(self):
        connections = self.app.connections
        memory = self.storage.memory
        folders = ("people", "locations", "topics", "projects", "daily")
        return (self.storage.revisions()[0], revision(*self.app.activity.paths, self.app.threads.index),
                self.app.brain_status(), bool(self.app.active_turns()),
                connections.scan_error, connections.found.copy(), connections.selected.copy(), connections.checks.copy(),
                self.app.memory_index.pinecone_status(self.app.agent.config),
                revision(memory, *(memory / name for name in folders)))

    def recent_checkpoints(self, now):
        checkpoints = self.app.checkpoints
        stamp = revision(checkpoints.root) if checkpoints.mode == "local" else ()
        cached = self.checkpoint_activity_cache
        if not cached or cached[0] != stamp or now >= cached[1]:
            try:
                rows = checkpoints.list()
            except HearthError:
                rows = []
            cached = stamp, now + timedelta(seconds=HEALTH_TTL), rows
            self.checkpoint_activity_cache = cached
        return cached[2]

    def activity(self, state, index, now, zone, pinecone):
        since = datetime.combine(now.astimezone(zone).date(), time.min, zone).astimezone(timezone.utc)
        until = datetime.combine(now.astimezone(zone).date() + timedelta(days=1), time.min, zone)
        logged = {row["message_id"] for row in state.get("activity", []) if row["kind"] == "recall" and row.get("message_id")}
        threads = self.app.threads
        with self.activity_lock:
            checkpoints = self.recent_checkpoints(now)
            count, errors, items = recent_activity(state, checkpoints, pinecone,
                bool(self.app.agent.config.get("agentmail", {}).get("connection_id")), since, until)
            cache = {}
            for thread_id in index:
                stamp = revision(threads.path(thread_id))
                if thread_id == MAIN and stamp == (None,):
                    stamp = revision(self.storage.state)
                key = stamp, since
                cached = self.chat_activity_cache.get(thread_id)
                if not cached or key != cached[0] or logged.intersection(cached[3]) != cached[4]:
                    messages = threads.recent_messages(thread_id, since, state.get("messages", ()))
                    rows = [row for row in chat_activity(messages, logged) if row[0]]
                    total = sum(since <= datetime.fromisoformat(row[0]) < until for row in rows)
                    recent = [(at, group, kind, {"content": title["content"]} if isinstance(title, dict) else title)
                              for at, group, kind, title in nlargest(ACTIVITY_SIZE, rows, key=activity_key)]
                    ids = {row["id"] for row in messages if row.get("id")}
                    cached = key, total, recent, ids, logged.intersection(ids)
                cache[thread_id] = cached
                count += cached[1]
                items.extend(cached[2])
            self.chat_activity_cache = cache
        return {"count": count, "errors": errors,
                "items": [{"at": at, "title": activity_title(title), "kind": kind}
                          for at, _, kind, title in nlargest(ACTIVITY_SIZE, items, key=activity_key)]}

    def settings(self):
        row = weather_state(self.storage.load())
        return {key: row[key] for key in ("location", "error")}

    def save_settings(self, body):
        if body.keys() != {"location"}:
            raise HearthError("Enter a weather location.")
        location = panels.text(body["location"], 120)
        if len(location) < 2:
            raise HearthError("Enter a city, region or postal code.")
        with self.storage.lock():
            state = self.storage.load()
            if weather_state(state)["location"] != location:
                state["weather"] = {"location": location, "revision": new_id(),
                                    "place": DEFAULT_PLACE if location.casefold() == DEFAULT_LOCATION.casefold() else None}
                self.storage.save(state)
        self.kick()
        return self.settings()

    def refresh_weather(self, clock=None, *, due=False):
        now = clock or datetime.now(timezone.utc)
        if not self.weather_lock.acquire(blocking=False):
            return False
        try:
            row = weather_state(self.storage.load())
            attempted = row["attempted_at"]
            interval = WEATHER_RETRY_MINUTES if row["error"] else WEATHER_MINUTES
            if due and attempted and datetime.fromisoformat(attempted) + timedelta(minutes=interval) > now:
                return False
            if self.app.restoring():
                return False
            try:
                place, value = weather_value(row)
                changes = {"place": place, "value": value, "updated_at": iso(clock), "error": None}
            except HearthError as error:
                changes = {"error": str(error)}
            except (OSError, HTTPException, ValueError, KeyError, TypeError):
                changes = {"error": "Open-Meteo weather is unavailable. Try refreshing."}
            with self.storage.lock():
                state = self.storage.load()
                if self.app.restoring() or weather_state(state)["revision"] != row["revision"]:
                    return False
                state["weather"] = {**row, **changes, "attempted_at": iso(clock)}
                self.storage.save(state)
                return True
        finally:
            self.weather_lock.release()

    def run_due(self, clock=None):
        if self.app.restoring() or not self.worker_lock.acquire(blocking=False):
            return 0
        try:
            count = self.panels.run_due(clock)
            return count + self.refresh_weather(clock, due=True)
        finally:
            self.worker_lock.release()

    def kick(self):
        # A held worker lock means the next scheduler pass can pick up any newly due items.
        if not self.worker_lock.locked():
            threading.Thread(target=self.run_due, daemon=True, name="hearth-home-refresh").start()

    def snapshot(self, clock=None):
        if clock is None:
            return self.app.home_poll()[0]
        return self.build_snapshot(clock)[0]

    def build_snapshot(self, now):
        with self.storage.lock():
            state = self.storage.load()
            if approvals.expire(state, now):
                self.storage.save(state)
            index = self.app.threads.load_index()
        config = saved(state)
        quiet = quiet_until(now, config)
        jobs = sorted((item for item in state["jobs"] if item["status"] == "scheduled"),
                      key=lambda item: item.get("next_fire_at") or item["next_at"])
        inbox = sorted((card for card in state.get("inbox", {}).values() if card["status"] == "review"),
                       key=lambda card: card["received_at"], reverse=True)
        pinecone = self.app.memory_index.pinecone_status(self.app.agent.config)
        zone = ZoneInfo(config["timezone"])
        weather = weather_state(state)
        built = {
            "today": {"quiet_until": iso(quiet) if quiet else None,
                      "quiet_enabled": config["quiet_start"] != config["quiet_end"],
                      "quiet_start": config["quiet_start"], "quiet_end": config["quiet_end"],
                      "jobs": [{"message": job["message"], "at": job.get("next_fire_at") or job["next_at"]}
                               for job in jobs[:3]]},
            "inbox": {"count": len(inbox), "items": [{"title": card.get("subject") or card.get("proposal", {}).get("title")
                                                     or "Untitled message", "at": card["received_at"]}
                                                    for card in inbox[:3]]},
            "files": {"items": recent_artifacts(state)},
            "memory": {"count": len(self.storage.files()), "last_sync": pinecone["last_sync"],
                       "pinecone": pinecone["state"], "record_count": pinecone["record_count"]},
            "activity": self.activity(state, index, now, zone, pinecone),
            "connections": self.app.connections.health(pinecone),
            "weather": {key: weather[key] for key in ("location", "value", "updated_at", "attempted_at", "error")}
                       | {"name": (weather["place"] or {}).get("name", weather["location"])},
        }
        from .goals import list_goals
        from .workers import ACTIVE

        built["goals"] = {"items": list_goals(state)}

        pending = [row for row in reversed(state["actions"].values()) if row.get("tool") and row["status"] == "pending"]
        active_workers = [row for row in state.get("workers", {}).values() if row["status"] in ACTIVE]
        active_work = bool(active_workers or self.app.active_turns() or any(
            row["status"] in {"pending", "changing"} for row in state["actions"].values()))
        # Quiet hours and the daily activity count can change without a storage write.
        minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        expires = min([minute, *(datetime.fromisoformat(row["expires_at"]) for row in pending)])
        return (scrub({"layout": panels.layout(state), "builtin": built, "panels": state.get("panels", {}),
                      "workers": active_workers, "active_work": active_work,
                      "timezone": config["timezone"], "clock_zone": str(PACIFIC), **self.app.brain_status()}) | {
                          "approvals": pending}, expires)

    def adjust(self, body):
        with self.storage.lock():
            state = self.storage.load()
            previous = panels.layout(state)
            result = panels.adjust_layout(state, body)
            if result != previous:
                operation, identity = body["operation"], body["id"]
                label = {"move": "Panel moved", "hide": "Panel removed", "restore": "Panel restored"}[operation]
                state.setdefault("activity", []).append(timeline.entry(
                    "panel", f"Home layout · {label}", {"thread_id": "", "thread_title": "Workspace"},
                    id=new_id(), at=iso(), data={"panel_id": identity, "operation": operation},
                ))
            self.storage.save(state)
            return result

    def toggle(self, body):
        with self.storage.lock():
            state = self.storage.load()
            row = panels.panel(state, body.get("id"))
            if row["kind"] != "checklist" or row["source"]["type"] != "static":
                raise HearthError("Only a static checklist can be checked off here.")
            index, checked = body.get("index"), body.get("checked")
            items = row["source"]["value"]
            if body.get("revision") != row["revision"]:
                raise HearthError("This checklist changed. Refresh Home and try again.")
            if type(index) is not int or not 0 <= index < len(items) or type(checked) is not bool:
                raise HearthError("Choose a checklist item and its checked state.")
            items[index]["checked"] = checked
            row.update(panels.initial_values(row, datetime.now(timezone.utc)), revision=new_id())
            self.storage.save(state)
            return row

    def panel_chat(self, identity):
        if isinstance(identity, str) and identity in TITLES:
            title, value = TITLES[identity], self.snapshot()["builtin"][identity]
        else:
            row = panels.panel(self.storage.load(), identity)
            title = row["title"]
            value = {key: row[key] for key in ("kind", "value", "updated_at", "error")}
        with self.storage.lock():
            return self.app.threads.create(title=f"About {title}"[:80],
                                           panel_context={"title": title, "snapshot": value})
