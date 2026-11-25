import re
import time
from datetime import datetime, timedelta, timezone

from .storage import HearthError, Storage, iso, new_id


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


def next_cron(expression, now):
    try:
        fields = expression.split()
        minutes, hours, days, months, weekdays = [
            cron_field(field, low, high)
            for field, (low, high) in zip(fields, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)], strict=True)
        ]
    except ValueError:
        raise HearthError("Use a five-field UTC cron expression, such as 0 17 * * 4.") from None
    weekdays = {day % 7 for day in weekdays}
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
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
                if at > now:
                    return at
    raise HearthError("That cron expression has no upcoming occurrence.")


def add_job(state, message, clock=None, *, at=None, cron=None):
    now = clock or datetime.now(timezone.utc)
    if not isinstance(message, str) or not message.strip() or len(message) > 800:
        raise HearthError("Provide a reminder of 1–800 characters.")
    if bool(at) == bool(cron):
        raise HearthError("Choose an ISO date or a recurring schedule.")
    if cron:
        if not isinstance(cron, str) or len(cron) > 100:
            raise HearthError("Provide a valid UTC cron expression.")
        due = next_cron(cron, now)
    else:
        try:
            due = datetime.fromisoformat(at)
            if due.tzinfo is None or due <= now:
                raise ValueError
            due = due.astimezone(timezone.utc)
        except (TypeError, ValueError):
            raise HearthError("Use a future ISO date with a time zone.") from None
    job = {"id": new_id(), "message": message.strip(), "next_at": iso(due), "cron": cron, "status": "scheduled"}
    state["jobs"].append(job)
    return job


def run_due(storage, clock=None):
    now = clock or datetime.now(timezone.utc)
    with storage.lock():
        state = storage.load()
        due = [job for job in state["jobs"] if job["status"] == "scheduled"
               and datetime.fromisoformat(job["next_at"]) <= now]
        for job in due:
            state["reminders"].append({
                "id": new_id(), "message": job["message"], "scheduled_at": job["next_at"], "delivered_at": iso(now)
            })
            if job["cron"]:
                job["next_at"] = iso(next_cron(job["cron"], now))
            else:
                job["status"] = "complete"
        if due:
            storage.save(state)
        return len(due)


def main():
    storage = Storage()
    while True:
        run_due(storage)
        time.sleep(2)


if __name__ == "__main__":
    main()
