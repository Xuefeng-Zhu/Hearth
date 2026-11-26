"""Recurring agent schedules, run claims, and delivery."""

import hashlib
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from queue import Empty
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .connectors import ConnectorError
from .gateway_tools import redact_text
from .reminder_config import CHANNELS, DEFAULTS, quiet_until, saved
from .scheduler import next_cron
from .storage import HearthError, iso, new_id

SOURCE = "recurring-task"
BRIEF_ID = "morning-brief"
BRIEF_NAME = "Morning brief"
OLD_BRIEF = "Give me a brief of my reminders, local weather, and top AI news."
BRIEF_INSTRUCTION = "Summarize today’s reminders, For you suggestions, local weather, and pending approvals."
ZONE = DEFAULTS["timezone"]
SCHEDULES = ("once", "daily", "weekly", "interval", "cron")
DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
FIELDS = {"name", "instruction", "schedule", "timezone", "delivery", "enabled"}
CREATE_REQUEST = re.compile(
    r"\b(?:every\s+(?:weekdays?|weekends?|day|week|morning|night|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d+\s+(?:minutes?|hours?|days?))"
    r"|recurring tasks?|daily (?:brief|task|summary)|weekly (?:brief|task|summary))\b", re.I)
NATURAL = re.compile(r"^(?:please\s+)?every\s+(weekday|weekend|day|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                     r"\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?[, ]+(.+)$", re.I | re.S)
INTERVAL = re.compile(r"^(?:please\s+)?every\s+(\d+)\s+(minutes?|hours?|days?)[, ]+(.+)$", re.I | re.S)


def natural(prompt):
    if match := NATURAL.fullmatch(prompt.strip()):
        day, hour, minute, part, instruction = match.groups()
        hour, minute = int(hour), int(minute or 0)
        if part:
            if not 1 <= hour <= 12:
                raise HearthError("Use a time such as 8 AM or 20:00.")
            hour = hour % 12 + (12 if part.casefold() == "pm" else 0)
        day = day.casefold()
        days = {"weekday": [1, 2, 3, 4, 5], "weekend": [0, 6]}
        schedule = {"type": "daily" if day == "day" else "weekly", "time": f"{hour:02d}:{minute:02d}"}
        if day != "day":
            schedule["days"] = days[day] if day in days else [next(i for i, name in enumerate(DAYS) if name.lower() == day)]
    elif match := INTERVAL.fullmatch(prompt.strip()):
        count, unit, instruction = match.groups()
        schedule = {"type": "interval", "minutes": int(count) * {"m": 1, "h": 60, "d": 1440}[unit[0].lower()]}
    else:
        return None
    name = instruction.strip().rstrip(".")[:80]
    return {"name": name, "instruction": instruction, "schedule": schedule}


def zone_for(value):
    try:
        return ZoneInfo(value)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise HearthError("Use an IANA time zone such as America/Los_Angeles.") from None


def next_run(schedule, zone, after, *, previous=None):
    kind = schedule["type"]
    if kind == "once":
        at = datetime.fromisoformat(schedule["at"])
        return at if at > after else None
    if kind == "interval":
        period = timedelta(minutes=schedule["minutes"])
        if previous and previous <= after:
            return previous + period * ((after - previous) // period + 1)
        return after + period
    return next_cron(schedule["cron"], after, zone=zone)


def clean_fields(fields, now, *, before=None):
    if fields.keys() - FIELDS:
        raise HearthError("Choose valid recurring task fields.")
    before = before or {}
    row = {key: fields.get(key, before.get(key)) for key in ("name", "instruction", "schedule", "timezone", "delivery", "enabled")}
    for key, limit in (("name", 80), ("instruction", 4000)):
        value = row[key]
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise HearthError(f"Enter a {key} of 1–{limit} characters.")
        row[key] = redact_text(value.strip())
    row["timezone"] = row["timezone"] if row["timezone"] is not None else ZONE
    row["delivery"] = row["delivery"] if row["delivery"] is not None else "app"
    row["enabled"] = row["enabled"] if row["enabled"] is not None else True
    zone = zone_for(row["timezone"])
    if not isinstance(row["delivery"], str) or row["delivery"] not in CHANNELS or type(row["enabled"]) is not bool:
        raise HearthError("Choose In app, Email, or Both and a valid enabled state.")
    if before and ("schedule" not in fields or fields["schedule"] == before["schedule"]):
        return row
    schedule = row["schedule"]
    if not isinstance(schedule, dict) or schedule.get("type") not in SCHEDULES:
        raise HearthError("Choose Once, Daily, Weekly, Interval, or Cron.")
    kind = schedule["type"]
    clean = {"type": kind}
    if kind == "once":
        try:
            at = datetime.fromisoformat(schedule.get("at", ""))
            if at.tzinfo is None:
                local = at.replace(tzinfo=zone)
                if local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != at:
                    raise ValueError
                at = local
            if at <= now:
                raise ValueError
        except (ValueError, TypeError):
            raise HearthError("Choose a future date and time that exists in your time zone.") from None
        clean["at"] = iso(at.astimezone(timezone.utc))
    elif kind == "interval":
        minutes = schedule.get("minutes")
        if type(minutes) is not int or not 1 <= minutes <= 525600:
            raise HearthError("Enter an interval from 1 to 525,600 minutes.")
        clean["minutes"] = minutes
    elif kind == "cron":
        expression = schedule.get("cron")
        if not isinstance(expression, str) or len(expression) > 100:
            raise HearthError("Enter a five-field cron expression.")
        clean["cron"] = " ".join(expression.split())
    else:
        at = schedule.get("time")
        days = schedule.get("days") if kind == "weekly" else list(range(7))
        if not isinstance(at, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", at):
            raise HearthError("Enter a local time in HH:MM format.")
        if not isinstance(days, list) or not days or any(type(day) is not int or not 0 <= day <= 6 for day in days):
            raise HearthError("Select at least one day from Sunday through Saturday.")
        hour, minute = map(int, at.split(":"))
        clean.update(time=at, cron=f"{minute} {hour} * * " + ",".join(map(str, sorted(set(days)))))
        if kind == "weekly":
            clean["days"] = sorted(set(days))
    row["schedule"] = clean
    if kind == "cron":
        try:
            next_run(clean, zone, now)
        except HearthError:
            raise HearthError("Enter a five-field cron expression with an upcoming local occurrence.") from None
    return row


def preview(row, now):
    zone = zone_for(row["timezone"])
    upcoming = []
    for _ in range(3):
        now = next_run(row["schedule"], zone, now)
        if now is None:
            break
        upcoming.append(iso(now.astimezone(zone)))
    return upcoming


def seed(state, now):
    rows = state.setdefault("recurring_tasks", {})
    brief = rows.get(BRIEF_ID)
    duplicates = [row for identity, row in rows.items() if identity != BRIEF_ID and not row.get("deleted")
                  and row["name"].strip().casefold() == BRIEF_NAME.casefold()
                  and row["instruction"] in {OLD_BRIEF, BRIEF_INSTRUCTION}]
    if brief and (brief["instruction"] not in {OLD_BRIEF, BRIEF_INSTRUCTION}
                  or brief["name"].casefold() != BRIEF_NAME.casefold()):
        return False
    if not brief and not duplicates:
        row = clean_fields({"name": BRIEF_NAME, "instruction": BRIEF_INSTRUCTION,
                            "schedule": {"type": "weekly", "days": [1, 2, 3, 4, 5], "time": "08:00"},
                            "enabled": False}, now)
        rows[BRIEF_ID] = {**row, "id": BRIEF_ID, "created_at": iso(now), "last_run": None, "next_run": None}
        return True
    if not duplicates and brief["instruction"] == BRIEF_INSTRUCTION:
        return False
    active = next((row for row in duplicates if row["enabled"] or row.get("manual_due")), None)
    if not brief or (active and not brief["enabled"] and not brief.get("deleted") and not brief.get("last_run")):
        brief = active or duplicates[0]
    rows[BRIEF_ID] = {**brief, "id": BRIEF_ID, "instruction": BRIEF_INSTRUCTION}
    for duplicate in duplicates:
        old = duplicate["id"]
        rows.pop(old)
        for collection in ("task_runs", "task_notifications"):
            for row in state.get(collection, {}).values():
                if row.get("task_id") == old:
                    row["task_id"] = BRIEF_ID
    return True


def require(state, identity):
    row = state.get("recurring_tasks", {}).get(identity) if isinstance(identity, str) else None
    if not row or row.get("deleted"):
        raise HearthError("This recurring task does not exist.")
    return row


def describe(row, state, now):
    return {**row, "upcoming": preview(row, now),
            "runs": [run for run in reversed(list(state.get("task_runs", {}).values()))
                     if run["task_id"] == row["id"]][:10]}


def mutate(storage, operation, fields, *, clock=None, origin=None, watch=None, effect_id=None):
    now = clock or datetime.now(timezone.utc)
    fields = fields.copy()
    identity = fields.pop("id", None)
    with storage.lock():
        state = storage.load()
        seeded = seed(state, now)
        if operation == "list":
            if seeded:
                storage.save(state)
            rows = [describe(row, state, now) for row in state["recurring_tasks"].values() if not row.get("deleted")]
            return {"tasks": rows, "timezone": ZONE}
        before = None if operation == "create" or (operation == "preview" and identity is None) else require(state, identity)
        if operation == "create" and effect_id in state.get("recurring_tasks", {}):
            return describe(state["recurring_tasks"][effect_id], state, now)
        if watch and any(row.get("watch") == watch and not row.get("deleted")
                         for row in state.get("recurring_tasks", {}).values()):
            raise HearthError("That watcher already exists.")
        if operation in {"preview", "create", "update"}:
            if before and before.get("watch"):
                fields["instruction"] = before["instruction"]
            row = clean_fields(fields, now, before=before)
            if operation == "preview":
                return {**row, "upcoming": preview(row, now)}
            changed_schedule = not before or any(row[key] != before[key] for key in ("timezone", "schedule", "enabled"))
            if before:
                row = {**before, **row}
            else:
                row.update(id=effect_id or new_id(), created_at=iso(now), last_run=None, **(origin or {}))
                if watch:
                    row["watch"] = watch
            if changed_schedule:
                times = preview(row, now)
                row["next_run"] = iso(datetime.fromisoformat(times[0]).astimezone(timezone.utc)) if row["enabled"] and times else None
        elif operation == "pause":
            row = {**before, "enabled": False, "next_run": None}
        elif operation == "run":
            row = before
            active = any(run["task_id"] == identity and run["status"] in {"running", "retrying"}
                         for run in state.get("task_runs", {}).values())
            if not active and not row.get("manual_due"):
                row["manual_due"] = iso(now)
        elif operation == "delete":
            row = {**before, "deleted": True, "enabled": False, "next_run": None}
            row.pop("manual_due", None)
        else:
            raise HearthError("Choose a recurring task action.")
        state["recurring_tasks"][row["id"]] = row
        storage.save(state)
        return describe(row, state, now)


def undo_delete(storage, approval_id):
    now = datetime.now(timezone.utc)
    with storage.lock():
        state = storage.load()
        action = state["actions"].get(approval_id)
        row = state.get("recurring_tasks", {}).get(action.get("undo_task")) if action else None
        if not row or not row.get("deleted") or action.get("undone"):
            raise HearthError("This task deletion has no available Undo.")
        row.pop("deleted")
        row["enabled"] = action["task_was_enabled"]
        upcoming = preview(row, now) if row["enabled"] else []
        row["next_run"] = iso(datetime.fromisoformat(upcoming[0]).astimezone(timezone.utc)) if upcoming else None
        row["enabled"] = bool(upcoming)
        action.update(undone=True, undone_at=iso(now))
        storage.save(state)
        return row


def active_reminders(state):
    return [{"title": row["message"], "next_at": row["next_at"]} for row in state["jobs"]
            if row["status"] == "scheduled"][:40]


def notification(state, identity, row, now):
    hold = quiet_until(now, saved(state))
    state.setdefault("task_notifications", {}).setdefault(identity, {
        "id": identity, "created_at": iso(now), "visible_at": iso(hold or now), **row,
        "email_state": "queued" if row["delivery"] in {"email", "both"} else "off",
    })


def inbox_rows(state, now):
    return list(reversed([row for row in state.get("task_notifications", {}).values()
                          if row.get("source") != "proactivity" and datetime.fromisoformat(row["visible_at"]) <= now]))[:50]


def tool_failure(tools):
    successes = {item["tool"] for item in tools if item["status"] != "failed"}
    return next((item["reason"] for item in tools
                 if item["status"] == "failed" and item["tool"] not in successes), None)


class Runner:
    def __init__(self, app):
        self.app = app
        self.storage = app.storage
        self.worker = threading.Lock()

    def kick(self):
        if self.worker.acquire(blocking=False):
            threading.Thread(target=self.work, daemon=True).start()

    def work(self):
        try:
            self.tick()
        finally:
            self.worker.release()

    def due(self, now):
        with self.storage.lock():
            state = self.storage.load()
            seeded = seed(state, now)
            runs = state.setdefault("task_runs", {})
            for run in runs.values():
                if run["status"] == "running":
                    saved_reply = self.saved_reply(run)
                    tools = saved_reply.get("task_tools", [])
                    output = saved_reply.get("watch_observation") if run.get("watch") else saved_reply.get("content", "")
                    self.finish(state, run, now, output, tools,
                                (saved_reply.get("task_error") or tool_failure(tools)) if saved_reply and (not run.get("watch") or output or saved_reply.get("task_error"))
                                else "The previous attempt was interrupted.",
                                round((now - datetime.fromisoformat(run["started_at"])).total_seconds() * 1000))
                    seeded = True
            for run in runs.values():
                if run["status"] == "retrying" and datetime.fromisoformat(run["retry_at"]) <= now:
                    task = state["recurring_tasks"].get(run["task_id"])
                    if task and not task.get("deleted"):
                        run.update(status="running", attempts=run["attempts"] + 1)
                        self.ensure_thread(task, run)
                        self.storage.save(state)
                        return run
                    run.update(status="failed", reason="Task deleted before retry.")
                    seeded = True
            for task in state["recurring_tasks"].values():
                if task.get("deleted") or any(run["task_id"] == task["id"] and run["status"] == "retrying" for run in runs.values()):
                    continue
                manual = task.get("manual_due")
                due = manual or task.get("next_run")
                if not due or datetime.fromisoformat(due) > now:
                    continue
                key = hashlib.sha256(f"{task['id']}:{'manual' if manual else 'due'}:{due}".encode()).hexdigest()
                if manual:
                    task.pop("manual_due", None)
                else:
                    following = next_run(task["schedule"], zone_for(task["timezone"]), now, previous=datetime.fromisoformat(due))
                    task["next_run"] = iso(following) if following else None
                    if not following:
                        task["enabled"] = False
                task["last_run"] = iso(now)
                seeded = True
                if key in runs:
                    continue
                run = {"id": key, "task_id": task["id"], "status": "running", "scheduled_at": due,
                       "started_at": iso(now), "attempts": 1, "name": task["name"], "delivery": task["delivery"],
                       "instruction": task["instruction"], "tools": [], "output": ""}
                if task.get("watch"):
                    run["watch"] = task["watch"]
                self.ensure_thread(task, run)
                runs[key] = run
                self.storage.save(state)
                return run
            if seeded:
                self.storage.save(state)
        return None

    def saved_reply(self, run):
        thread = run["thread_id"]
        if thread not in self.app.threads.load_index():
            return {}
        return next((row for row in reversed(self.app.threads.messages(thread))
                     if row["role"] == "assistant" and row.get("task_run") == run["id"]
                     and row.get("task_attempt") == run["attempts"]), {})

    def ensure_thread(self, task, run):
        thread = task.get("chat_id")
        if thread not in self.app.threads.load_index():
            thread = self.app.threads.create(title=task["name"])["id"]
        run["thread_id"] = task["chat_id"] = thread

    def tick(self, clock=None):
        with self.app.reminders.exclusive("recurring-tasks") as acquired:
            if not acquired or self.app.restoring():
                return 0
            now = clock or datetime.now(timezone.utc)
            count = 0
            for _ in range(12):
                if not (run := self.due(now)):
                    break
                output, tools, reason, duration = self.run(run, now)
                with self.storage.lock():
                    state = self.storage.load()
                    current = state["task_runs"][run["id"]]
                    self.finish(state, current, now, output, tools, reason, duration)
                    self.storage.save(state)
                count += 1
            self.deliver(now)
            return count

    def run_brief(self, run, now):
        from . import approvals, home
        from .proactive_context import forget_rules, private_match, private_text

        self.app.home.refresh_weather(now, due=True)
        with self.storage.lock():
            state = self.storage.load()
            current = state["recurring_tasks"][BRIEF_ID]
            zone = zone_for(current["timezone"])
            date = now.astimezone(zone).date()
            rules = forget_rules(self.storage, state)
            labels = {}
            for row in [*state["jobs"], *state["reminders"]]:
                if row.get("status") == "canceled" or row.get("test"):
                    continue
                at = datetime.fromisoformat(row.get("scheduled_at") or row.get("next_fire_at") or row["next_at"])
                text = row["message"]
                if at.astimezone(zone).date() == date and not private_match(text, rules):
                    labels[at, private_text(text)] = f"{at.astimezone(zone).strftime('%H:%M')} · {private_text(text)}"
            cards = self.app.proactivity.cards(state, now)
            if approvals.expire(state, now):
                self.storage.save(state)
            pending = [row for row in state["actions"].values() if row["status"] == "pending"]
            weather = home.weather_state(state)
            forecast = "Current conditions unavailable."
            if weather["value"] and weather["updated_at"] and not private_match(weather["location"], rules):
                updated = datetime.fromisoformat(weather["updated_at"])
                if now - timedelta(hours=2) <= updated <= now:
                    place = (weather["place"] or {}).get("name", weather["location"])
                    if not private_match(place, rules):
                        condition = home.weather_label(weather["value"]["code"])
                        forecast = f"{private_text(place)} · {weather['value']['temperature']}°F, {condition.lower()}."
            def section(title, values, empty):
                return f"**{title}**\n" + ("\n".join(f"- {value}" for value in values) if values else empty)

            brief = "\n\n".join((
                section("Today’s reminders", [labels[key] for key in sorted(labels)][:20], "Nothing scheduled today."),
                section("For you", [f"{card['title']} · {card['why']}" for card in cards], "No current suggestions."),
                f"**Weather**\n{forecast}",
                section("Waiting on approval", [f"{private_text(row['title'])} · {private_text(row.get('thread_title', 'Main'))}"
                                                for row in pending[:20]
                                                if not private_match(row["title"] + " " + row.get("thread_title", ""), rules)],
                        "No visible pending approvals."),
            ))
            fields = {"source": SOURCE, "task_run": run["id"], "task_attempt": run["attempts"]}
            self.app.threads.append(run["thread_id"], "user", BRIEF_INSTRUCTION, **fields)
            self.app.threads.append(run["thread_id"], "assistant", brief, **fields)
        return brief

    def run(self, run, now=None):
        started = time.monotonic()
        output, reason, tools, done = "", None, [], False
        try:
            if run["task_id"] == BRIEF_ID and run["instruction"] == BRIEF_INSTRUCTION:
                return self.run_brief(run, now or datetime.now(timezone.utc)), [], None, round((time.monotonic() - started) * 1000)
            if run.get("watch"):
                from .watchers import observe
                return observe(run["watch"]), [], None, round((time.monotonic() - started) * 1000)
            events = self.app.enqueue(run["thread_id"], run["instruction"], source=SOURCE, task_run=run["id"])
            while (event := events.get(timeout=90)) is not None:
                name, data = event
                if name == "done":
                    done, output = True, data["message"]["content"]
                elif name == "error":
                    reason = data["message"]
                elif name == "tool_result":
                    tools.append(data)
            if not done and not reason:
                reason = "The brain returned no result."
            reason = reason or tool_failure(tools)
        except Empty:
            # Keep the run claimed while its chat turn is still active.
            while events.get() is not None:
                pass
            reason = "The brain timed out."
        except (HearthError, OSError) as error:
            reason = str(error)
        return output, tools, reason, round((time.monotonic() - started) * 1000)

    def finish(self, state, run, now, output, tools, reason, duration=0):
        from . import timeline

        status = ("retrying" if run["attempts"] == 1 else "failed") if reason else (
            "approval_needed" if any(tool["status"] == "pending" for tool in tools) else "complete")
        notify = True
        if run.get("watch") and not reason:
            from .watchers import report
            task = state["recurring_tasks"].get(run["task_id"], {})
            if task.get("deleted"):
                output, notify = "Watcher deleted before this check completed.", False
            else:
                previous = task.get("watch_baseline")
                observation = task["watch_baseline"] = output
                notify = bool(previous and previous["signature"] != observation["signature"])
                output = (report(run["watch"], previous, observation) if notify else
                          "No change detected." if previous else "Baseline saved.")
                if notify and not self.saved_reply(run) and run["thread_id"] in self.app.threads.load_index():
                    self.app.threads.append(run["thread_id"], "assistant", output, source=SOURCE,
                                            task_run=run["id"], task_attempt=run["attempts"],
                                            watch_observation=observation)
        run.update(status=status, output=output, tools=tools, reason=reason, duration_ms=duration, finished_at=iso(now))
        if status == "complete":
            from . import goals
            goals.complete_linked(state, "task", run["task_id"], now)
        if status == "retrying":
            run["retry_at"] = iso(now + timedelta(minutes=1))
        else:
            run.pop("retry_at", None)
            if status == "failed" and run["thread_id"] in self.app.threads.load_index():
                reply = self.saved_reply(run)
                if not reply.get("task_error"):
                    self.app.threads.append(run["thread_id"], "assistant", f"Task failed after two attempts. {reason}",
                                            source=SOURCE, task_run=run["id"], task_attempt=run["attempts"], task_error=reason)
            origin = {"thread_id": run["thread_id"], "thread_title": run["name"], "source": SOURCE}
            if notify:
                notification(state, run["id"], {
                    "title": run["name"], **origin, "delivery": run["delivery"], "status": status,
                    "text": reason or output, "task_id": run["task_id"],
                }, now)
        state.setdefault("activity", []).append(timeline.entry(
            "task", f"{run['name']} · {status.replace('_', ' ')}", run,
            id=new_id(), at=iso(now), error=status == "failed",
            data={"status": status, "reason": reason, "duration_ms": duration, "task_id": run["task_id"]}))

    def deliver(self, now):
        from . import proactivity

        for _ in range(12):
            with self.storage.lock():
                state = self.storage.load()
                notifications = state.get("task_notifications", {}).values()
                interrupted = [item for item in notifications if item["email_state"] == "sending"]
                for item in interrupted:
                    item.update(email_state="failed", email_reason="Delivery was interrupted and could not be confirmed.")
                if interrupted:
                    self.storage.save(state)
                row = next((item for item in notifications
                            if item["email_state"] == "queued" and datetime.fromisoformat(item["visible_at"]) <= now
                            and datetime.fromisoformat(item.get("email_next", item["visible_at"])) <= now), None)
                if not row:
                    return
                selection = saved(state)
                if hold := quiet_until(now, selection):
                    row["email_next"] = iso(hold)
                    self.storage.save(state)
                    continue
                digest = row.get("source") == proactivity.SOURCE
                if digest:
                    preferences = proactivity.settings(state)
                    if not (preferences["enabled"] and preferences["email_digest"]) or row["date"] != proactivity.day_key(now):
                        row.update(email_state="off")
                        self.storage.save(state)
                        continue
                    if hold := proactivity.hold(now, preferences):
                        row["email_next"] = iso(hold)
                        self.storage.save(state)
                        continue
                    shown = state.get("proactivity", {}).get("cards", {})
                    cards = [card for card in self.app.proactivity.cards(state, now)
                             if proactivity.day_key(datetime.fromisoformat(shown[card["id"]]["shown_at"])) == row["date"]]
                    if not cards:
                        row.update(email_state="off")
                        self.storage.save(state)
                        continue
                row.setdefault("recipient", selection["recipient"])
                row["email_state"] = "sending"
                self.storage.save(state)
            reason = None
            try:
                if not row["recipient"] or row["recipient"] != selection["recipient"]:
                    raise HearthError("Set a recipient in Settings → Reminders.")
                client = self.app.reminders.client()
                mailbox = self.app.reminders.mailbox(client)
                url = self.app.reminders.base
                body = ("\n\n".join(f"{card['title']}\n{card['why']}" for card in cards) if digest
                        else row["text"] or "Open Hearth to review the run.")
                if url:
                    link = f"{url}/" if digest else f"{url}/?thread={row['thread_id']}"
                    body += f"\n\nOpen Hearth: {link}"
                label = "hearth-proactivity" if digest else "hearth-task"
                receipt = client.send(mailbox, {"to": [row["recipient"]], "subject": f"Hearth: {row['title']}",
                                                "text": body, "labels": [label]}, f"{label}-{row['id']}")
                if not receipt.get("message_id"):
                    raise HearthError("AgentMail returned no delivery receipt.")
            except (HearthError, ConnectorError) as error:
                reason = str(error) if isinstance(error, HearthError) else "AgentMail could not confirm delivery."
            with self.storage.lock():
                state = self.storage.load()
                current = state["task_notifications"][row["id"]]
                current.update(email_state="failed" if reason else "sent", email_reason=reason)
                self.storage.save(state)
