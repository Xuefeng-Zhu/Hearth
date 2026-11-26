import fcntl
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import delivery_journal
from .gateway_tools import redact_text
from .reminder_config import CHANNELS, quiet_until, saved
from .storage import HearthError, Storage, iso, new_id
from .threads import MAIN_ORIGIN

RESTORE_DRAIN_SECONDS = 2


@contextmanager
def workspace_lock(storage, name, *, wait=False, shared=False, timeout=None):
    with (storage.root / f"{name}.lock").open("a") as file:
        flags = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(file, flags | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                if deadline is None or time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.01)
            else:
                yield True
                return


def claims(storage):
    return workspace_lock(storage, "scheduler-restore", shared=True)


def reconcile(state, rows):
    activity_ids = {event.get("id") for event in state.get("activity", [])} if rows else set()
    changed = False
    for item in email_records(state):
        if item.get("delivery", {}).get("email") and (row := rows.get(delivery_journal.key(item))):
            changed |= delivery_journal.project(state, item, row, activity_ids)
    return changed, activity_ids


def due_email(item, now):
    email = item.get("delivery", {}).get("email", {})
    return email.get("status") == "queued" and datetime.fromisoformat(email["next_at"]) <= now


def hold_email(state, item, now, selection):
    email = item["delivery"]["email"]
    if item["urgent"] or email.get("attempts") or not (held := quiet_until(now, selection)):
        return False
    from .reminders import log
    email.update(next_at=iso(held), reason="Quiet hours")
    log(state, "Email queued · Quiet hours", item, now, provider="agentmail",
        data={"reminder_id": item["id"], "next_due": iso(held), "status": "queued"})
    return True


def cron_field(field, low, high):
    values = set()
    for part in field.split(","):
        match = re.fullmatch(r"(\*|\d+)(?:-(\d+))?(?:/(\d+))?", part)
        if not match:
            raise ValueError
        start, end, step = match.groups()
        first = low if start == "*" else int(start)
        last = int(end) if end else high if start == "*" or step else first
        stride = int(step or 1)
        if not low <= first <= last <= high or stride < 1 or (start == "*" and end):
            raise ValueError
        values.update(range(first, last + 1, stride))
    return sorted(values)


def next_cron(expression, now, *, zone=None):
    try:
        fields = expression.split()
        minutes, hours, days, months, weekdays = [
            cron_field(field, low, high)
            for field, (low, high) in zip(fields, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)], strict=True)
        ]
    except ValueError:
        raise HearthError("Use a five-field UTC cron expression, such as 0 17 * * 4.") from None
    weekdays = {day % 7 for day in weekdays}
    day = (now.astimezone(zone) if zone else now).replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(366 * 9):
        date = day + timedelta(days=offset)
        day_match = date.day in days
        weekday_match = (date.weekday() + 1) % 7 in weekdays
        matches = (day_match and weekday_match if any(field.startswith("*") for field in (fields[2], fields[4]))
                   else day_match or weekday_match)
        if date.month not in months or not matches:
            continue
        for hour in hours:
            for minute in minutes:
                at = date.replace(hour=hour, minute=minute)
                if zone:
                    instant = at.astimezone(timezone.utc)
                    # A spring-forward wall time does not occur. Use the first fold in fall.
                    if instant > now and instant.astimezone(zone).replace(tzinfo=None) == at.replace(tzinfo=None):
                        return instant
                elif at > now:
                    return at
    raise HearthError("That cron expression has no upcoming occurrence.")


def add_job(state, message, clock=None, *, at=None, cron=None, origin=None, channel=None, urgent=False, note="", identity=None,
            timezone_name=None):
    now = clock or datetime.now(timezone.utc)
    if not isinstance(message, str) or not message.strip() or len(message) > 800:
        raise HearthError("Provide a reminder of 1–800 characters.")
    if bool(at) == bool(cron):
        raise HearthError("Choose an ISO date or a recurring schedule.")
    if cron:
        if not isinstance(cron, str) or len(cron) > 100:
            raise HearthError("Provide a valid UTC cron expression.")
        due = next_cron(cron, now, zone=ZoneInfo(timezone_name) if timezone_name else None)
    else:
        try:
            due = datetime.fromisoformat(at)
            if due.tzinfo is None or due <= now:
                raise ValueError
            due = due.astimezone(timezone.utc)
        except (TypeError, ValueError):
            raise HearthError("Use a future ISO date with a time zone.") from None
    channel = saved(state)["channel"] if channel is None else channel
    if not isinstance(channel, str) or channel not in CHANNELS or type(urgent) is not bool:
        raise HearthError("Choose In app, Email, or Both and a valid urgency.")
    if not isinstance(note, str) or len(note) > 4_000:
        raise HearthError("Provide a note of at most 4,000 characters.")
    job = {"id": identity or new_id(), "message": redact_text(message.strip()), "note": redact_text(note.strip()),
           "next_at": iso(due), "next_fire_at": iso(due), "created_at": iso(now), "cron": cron, "status": "scheduled",
           "channel": channel, "urgent": urgent, **(origin or MAIN_ORIGIN)}
    if timezone_name:
        job["timezone"] = timezone_name
    state["jobs"].append(job)
    next_due(state)
    return job


def email_records(state):
    return state["reminders"] + state.get("reminder_tests", [])


def pending_occurrences(state, job):
    return [item for item in state["reminders"] if item.get("job_id") == job["id"]
            and (not job["cron"] or any(info.get("status") == "queued" for info in item.get("delivery", {}).values()))]


def can_cancel(state, job):
    occurrences = pending_occurrences(state, job)
    active = job["status"] == "scheduled" or (job["status"] == "complete" and bool(occurrences))
    deliveries = [info for item in occurrences
                  for info in item.get("delivery", {"app": {"status": "sent"}}).values()]
    if not active or any(info.get("uncertain") or info.get("sending") for info in deliveries):
        return False
    return (job["status"] == "scheduled" or any(info["status"] == "queued" for info in deliveries)
            or not any(info["status"] == "sent" for info in deliveries))


def next_due(state):
    times = [job.get("next_fire_at", job["next_at"]) for job in state["jobs"] if job["status"] == "scheduled"]
    times.extend(email["next_at"] for item in email_records(state)
                 if (email := item.get("delivery", {}).get("email")) and email["status"] == "queued")
    state["next_fire_at"] = min(times, default=None)
    return state["next_fire_at"]


def occurrence(job, now, *, test=False):
    due = job["next_at"]
    late = max(0, int((now - datetime.fromisoformat(due)).total_seconds() // 60))
    delivery = {name: {"status": "sent", "at": iso(now)} if name == "app" else
                {"status": "queued", "next_at": iso(now), "attempts": 0}
                for name in CHANNELS[job.get("channel", "app")]}
    return {"id": new_id(), "job_id": job["id"], "message": job["message"], "note": job.get("note", ""),
            "channel": job.get("channel", "app"), "urgent": job.get("urgent", False), "test": test,
            "scheduled_at": due, "delivered_at": iso(now), "late_minutes": late, "delivery": delivery,
            **{key: job.get(key, default) for key, default in MAIN_ORIGIN.items()},
            **{key: job[key] for key in ("source", "automation_path", "goal_id", "goal_checkin", "root_job_id") if key in job}}


def claim_due(storage, clock=None, *, tick=False):
    now = clock or datetime.now(timezone.utc)
    with claims(storage) as allowed:
        if not allowed:
            return {"fired": 0, "queued_deliveries": 0, "last_tick": None, "next_due": None}
        with storage.lock():
            state = storage.load()
            rows = delivery_journal.load(storage)
            changed, activity_ids = reconcile(state, rows)
            due = [job for job in state["jobs"] if job["status"] == "scheduled"
                   and datetime.fromisoformat(job.get("next_fire_at", job["next_at"])) <= now]
            fired = 0
            for job in due:
                if job.get("goal_id"):
                    from .goals import goal_job_due
                    if not goal_job_due(state, job):
                        job.update(status="canceled", next_fire_at=None)
                        continue
                item = occurrence(job, now)
                if row := rows.get(delivery_journal.key(item)):
                    delivery_journal.project(state, item, row, activity_ids)
                fired += 1
                state["reminders"].append(item)
                if state.get("event_automations"):
                    from . import event_automations
                    event_automations.enqueue(state, {
                        "type": "reminder", "id": item["id"], "at": item["delivered_at"], "job_id": job["id"],
                        "title": job["message"], "body": job.get("note", ""), "source": job.get("source"),
                        "automation_path": job.get("automation_path", []),
                    }, now)
                if job.get("snoozed_at"):
                    job.pop("snoozed_at")
                if job.get("cron"):
                    job["next_at"] = job["next_fire_at"] = iso(next_cron(
                        job["cron"], now, zone=ZoneInfo(job["timezone"]) if job.get("timezone") else None))
                else:
                    job["status"] = "complete"
                    job["next_fire_at"] = None
            queued = 0
            selection = saved(state)
            for item in email_records(state):
                if due_email(item, now):
                    if hold_email(state, item, now, selection):
                        changed = True
                    else:
                        queued += 1
            old = state.get("next_fire_at")
            new = next_due(state)
            if tick:
                state["last_tick"] = iso(now)
            if changed or due or old != new or tick:
                storage.save(state)
            return {"fired": fired, "queued_deliveries": queued, "last_tick": state.get("last_tick"), "next_due": new}


def run_due(storage, clock=None, *, tick=False):
    return claim_due(storage, clock, tick=tick)["fired"]


def main():
    storage = Storage()
    while True:
        run_due(storage)
        time.sleep(2)


if __name__ == "__main__":
    main()
