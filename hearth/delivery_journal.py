"""Reminder send intents and receipts that survive replacement of live/."""

import json
import os
from datetime import datetime

from .storage import atomic_write, iso, new_id

FILENAME = "reminder-delivery.json"


def key(item):
    return f"{item['job_id']}:{item['scheduled_at']}"


def load(storage):
    try:
        return json.loads((storage.root / FILENAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save(storage, rows):
    atomic_write(storage.root / FILENAME, json.dumps(rows, ensure_ascii=False))
    directory = os.open(storage.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def record(rows, item, email, *, event_at=None):
    email = {name: value for name, value in email.items() if name != "receipt_revision"}
    if email["status"] == "sent" and "target" in email:
        # Inbox replies authenticate against the original recipient and link lifetime.
        email["target"] = {name: email["target"][name] for name in ("recipient", "expires")}
    elif email["status"] == "failed" and not email.get("outbox"):
        email.pop("target", None)
        email.pop("send_inbox", None)
    row = {"id": item["id"], "email": email, "revision": new_id(), "written_at": iso()}
    if event_at:
        row["event_at"] = iso(event_at)
    rows[key(item)] = row
    return row


def mark_unfinished(rows):
    changed = False
    for row in rows.values():
        email = row["email"]
        if email.pop("sending", False):
            email.update(pending_reconcile=True, uncertain=True, reason="Confirming reminder delivery")
            row.update(revision=new_id(), written_at=iso())
            changed = True
    return changed


def adopt(rows, items):
    """Preserve attempts made before the delivery journal existed."""
    changed = False
    for item in items:
        email = item.get("delivery", {}).get("email", {})
        if email.get("attempts") and key(item) not in rows:
            record(rows, item, email)
            changed = True
    return changed


def project(state, item, row, activity_ids):
    delivery = item.get("delivery", {})
    if "email" not in delivery or delivery["email"].get("receipt_revision") == row["revision"]:
        return False
    item["id"] = row["id"]
    email = delivery["email"] = {**row["email"], "receipt_revision": row["revision"]}
    if email["status"] == "sent":
        item["late_minutes"] = max(item["late_minutes"], email.get("actual_late", 0))
    if row.get("event_at") and row["revision"] not in activity_ids:
        from .reminders import log, public_delivery
        log(state, f"Email {email['status']} · {item['message']}", item, datetime.fromisoformat(row["event_at"]),
            provider="agentmail", error=email["status"] == "failed", identity=row["revision"],
            data={"reminder_id": item["id"], "delivery": public_delivery({"email": email}),
                  "late_minutes": item["late_minutes"]})
        activity_ids.add(row["revision"])
    return True
