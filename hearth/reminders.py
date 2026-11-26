import hashlib
import hmac
import os
import re
import threading
import time
from calendar import month_abbr
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from . import delivery_journal, scheduler, timeline
from .agentmail import AgentMail
from .connectors import ConnectorError
from .reminder_config import CHANNELS, CHANNEL_LABELS, NOT_CONNECTED, equal, public_url, saved, secret, settings
from .scheduler import can_cancel, pending_occurrences
from .search_text import match_row
from .storage import HearthError, iso, new_id
from .threads import MAIN_ORIGIN

ACTIONS = {"done": "Done", "snooze-10": "Snooze 10 min", "snooze-60": "Snooze 1 h"}
TOKEN = re.compile(r"([a-f0-9]{32})\.(done|snooze-10|snooze-60)\.(\d{1,12})\.([a-f0-9]{64})")
LIFETIME = timedelta(days=7)
BACKOFF = (60, 300, 1800, 7200)
DELIVERY_TIMEOUT = 20
RESTORE_WORK = ("inbox-poll", "recurring-tasks", "event-automations")


def log(state, title, origin, now, *, data=None, provider=None, error=False, identity=None):
    state.setdefault("activity", []).append(timeline.entry(
        "reminder", title, origin, id=identity or new_id(), at=iso(now), data=data or {}, provider=provider, error=error))


def cancel(state, identity, now):
    job = next((job for job in state["jobs"] if job["id"] == identity), None)
    if not job or not can_cancel(state, job):
        raise HearthError("This reminder can no longer be canceled.")
    job.update(status="canceled", next_fire_at=None)
    for item in pending_occurrences(state, job):
        for delivery in item["delivery"].values():
            if delivery["status"] != "sent":
                delivery.update(status="canceled", reason="Canceled before send.")
    for action in state["actions"].values():
        if action.get("job", {}).get("id") == identity:
            action.update(undone=True, undone_at=iso(now))
    scheduler.next_due(state)
    log(state, f"Reminder canceled · {job['message']}", job, now, data={"job_id": identity})
    return job


def change_occurrence(state, item, operation, now, minutes=None):
    if item.get("action"):
        return item["action"]
    if operation == "done":
        label = "Done"
    else:
        minutes = minutes if minutes is not None else int(operation.removeprefix("snooze-"))
        due = now + timedelta(minutes=minutes)
        scheduler.add_job(state, item["message"], now, at=iso(due), channel=item["channel"],
                          urgent=item["urgent"], note=item["note"],
                          origin={**{key: item[key] for key in (*MAIN_ORIGIN, "source", "automation_path",
                                                                 "goal_id", "goal_checkin") if key in item},
                                  "root_job_id": item.get("root_job_id", item["job_id"])})["snoozed_at"] = iso(now)
        label = f"Snoozed {minutes} min"
    item["action"] = {"label": label, "at": iso(now)}
    if operation == "done" and not item.get("test"):
        from . import goals
        goals.complete_linked(state, "reminder", item.get("root_job_id", item["job_id"]), now)
    log(state, f"{label} · {item['message']}", item, now, data={"reminder_id": item["id"]})
    return item["action"]


def render_email(item, recipient, base, zone, action_token):
    def clean(value):
        return escape(value, quote=True)

    title, note = item["message"], item.get("note") or ""
    subject = " ".join(title.split())[:180]
    when = datetime.fromisoformat(item["scheduled_at"]).astimezone(ZoneInfo(zone))
    when_text = when.strftime("%a, %b %d, %Y at %I:%M %p %Z")
    late = f" · Late by {item['late_minutes']}m" if item.get("late_minutes") else ""
    thread = f"{base}/?{urlencode({'thread': item['thread_id']})}"
    links = [(label, f"{base}/reminder-action#{action_token(operation)}") for operation, label in ACTIONS.items()]
    text = "\n\n".join(filter(None, (title, when_text + late, note, f"Open Hearth thread: {thread}",
                                       "\n".join(f"{label}: {link}" for label, link in links))))
    buttons = " ".join(f'<a style="display:inline-block;margin:0 8px 8px 0;padding:10px 13px;'
                       f'border-radius:9px;background:#f5e8d9;color:#492717;text-decoration:none" '
                       f'href="{clean(link)}">{label}</a>' for label, link in links)
    body = (f'<div style="background:#f7f2ea;padding:32px 16px;color:#392a23;font:16px/1.6 system-ui,sans-serif">'
            f'<div style="max-width:540px;margin:auto;background:#fffdf8;border:1px solid #e6d9cd;'
            f'border-radius:18px;padding:32px"><p style="color:#884c30;font-weight:bold">Hearth · Reminder</p>'
            f'<h1 style="font:700 30px/1.2 Georgia,serif;margin:0 0 12px">{clean(title)}</h1>'
            f'<p style="color:#665247">{clean(when_text + late)}</p>'
            f'<p style="white-space:pre-wrap">{clean(note)}</p>'
            f'<p><a style="color:#884c30" href="{clean(thread)}">Open Hearth thread</a></p>'
            f'<div>{buttons}</div></div></div>')
    return {"to": [recipient] if recipient else [], "subject": f"Hearth reminder: {subject}", "text": text, "html": body}


def public_delivery(delivery):
    return {channel: {key: value for key, value in info.items()
                      if key in {"status", "reason", "at", "next_at", "attempts", "sending"}}
            for channel, info in delivery.items()}


def public_item(item):
    return {**item, "delivery": public_delivery(item.get("delivery", {"app": {"status": "sent"}}))}


def due_text(value, zone):
    try:
        when = datetime.fromisoformat(value)
        when = when.replace(tzinfo=when.tzinfo or timezone.utc).astimezone(zone)
    except (TypeError, ValueError, OverflowError):
        return "—"
    return (f"{month_abbr[when.month]} {when.day}, {when.year}, "
            f"{when.hour % 12 or 12}:{when.minute:02} {'PM' if when.hour >= 12 else 'AM'}")


def search_reminders(rows, query, zone, *, outbox=False):
    for row in rows:
        due = row.get("created_at") if outbox else row.get("next_at") or row.get("scheduled_at")
        row["due_text"] = due_text(due, zone)
        if query is None:
            yield row
            continue
        delivery = row.get("delivery", {})
        channel = row.get("channel", "email" if outbox else "")
        fields = {"title": row.get("subject" if outbox else "message"), "note": row.get("note"),
                  "due": row["due_text"], **{key: CHANNEL_LABELS[key] for key in delivery}}
        extra = (CHANNEL_LABELS.get(channel), due, row.get("cron"),
                 *(due_text(info.get("next_at"), zone) for info in delivery.values() if info.get("next_at")))
        if result := match_row(row, query, fields, extra):
            yield result


class Reminders:
    def __init__(self, app):
        self.app = app
        self.storage = app.storage
        self.tick_token = secret(self.storage, "scheduler-tick.token")
        self.signing_key = secret(self.storage, "reminder-action.key").encode()
        self.base = public_url(os.environ.get("HEARTH_PUBLIC_URL"))
        self.worker = threading.Lock()

    def recover(self):
        with self.exclusive("reminder-delivery") as acquired:
            if acquired:
                with scheduler.claims(self.storage) as allowed:
                    if allowed:
                        with self.storage.lock():
                            self.reconcile_locked(unfinished=True)

    def reconcile_locked(self, *, unfinished=False):
        state = self.storage.load()
        rows = delivery_journal.load(self.storage)
        changed = delivery_journal.adopt(rows, scheduler.email_records(state))
        if unfinished:
            changed |= delivery_journal.mark_unfinished(rows)
        if changed:
            delivery_journal.save(self.storage, rows)
        if scheduler.reconcile(state, rows)[0]:
            scheduler.next_due(state)
            self.storage.save(state)
        return rows

    def drain_for_restore(self):
        deadline = time.monotonic() + scheduler.RESTORE_DRAIN_SECONDS
        while True:
            active = []
            for name in (*RESTORE_WORK, "reminder-delivery"):
                with scheduler.workspace_lock(self.storage, name) as idle:
                    if not idle:
                        active.append(name)
            if not active:
                return
            if time.monotonic() >= deadline:
                if any(name in RESTORE_WORK for name in active):
                    raise HearthError("Scheduled work is still active. Try restoring again after it finishes.")
                return
            time.sleep(0.01)

    def config(self):
        return self.app.agent.config.get("agentmail", {})

    def client(self):
        config = self.config()
        if not config.get("connection_id"):
            raise HearthError(NOT_CONNECTED)
        return AgentMail(self.app.gateway, config)

    @contextmanager
    def exclusive(self, name, *, wait=False):
        with scheduler.workspace_lock(self.storage, name, wait=wait) as acquired:
            if acquired and name in RESTORE_WORK:
                # Register the job through its named lock before checking the restore gate.
                with scheduler.claims(self.storage) as allowed:
                    acquired = allowed
            yield acquired

    def mailbox(self, client):
        config = client.config
        key = f"{config['connection_id']}:{config.get('inbox_id', '')}"
        timeout = None if client.deadline is None else client.deadline - time.monotonic()
        with scheduler.workspace_lock(self.storage, "agentmail-inbox", wait=timeout is None,
                                      timeout=timeout) as acquired:
            if not acquired:
                raise ConnectorError("The AgentMail inbox lookup timed out.", 504)
            with self.storage.lock():
                old = self.storage.load().get("agentmail_inbox", {})
            if old.get("key") == key:
                return old
            inbox = {**client.ensure_inbox(), "key": key}
            with scheduler.claims(self.storage) as allowed:
                if allowed:
                    with self.storage.lock():
                        state = self.storage.load()
                        state["agentmail_inbox"] = inbox
                        self.storage.save(state)
            return inbox

    def info(self):
        with self.storage.lock():
            state = self.storage.load()
        config = self.config()
        inbox_config = f"{config.get('connection_id')}:{config.get('inbox_id', '')}"
        inbox = state.get("agentmail_inbox", {})
        connected = bool(config.get("connection_id"))
        return {"settings": saved(state), "connected": connected,
                "inbox_address": (inbox.get("address") if inbox.get("key") == inbox_config else None),
                "connection_message": "" if connected else NOT_CONNECTED,
                "inbox_error": state.get("inbox_poll", {}).get("error") if connected else None,
                "last_poll": state.get("inbox_poll", {}).get("at"),
                "last_tick": state.get("last_tick"), "next_due": scheduler.next_due(state)}

    def list(self, query=None):
        with self.storage.lock():
            state = self.storage.load()
        jobs_by_id = {job["id"]: job for job in state["jobs"]}
        jobs = [{**job, "cancelable": can_cancel(state, job),
                 "delivery": {name: {"status": "queued"} for name in CHANNELS[job.get("channel", "app")]}}
                for job in state["jobs"] if job["status"] == "scheduled"]
        delivered = [{**public_item(item), "cancelable": not item.get("test") and
                      bool((job := jobs_by_id.get(item.get("job_id"))) and can_cancel(state, job))}
                     for item in scheduler.email_records(state)]
        outbox = [{key: entry[key] for key in ("id", "subject", "created_at", "reason")}
                  for entry in state["outbox"] if entry.get("kind") == "reminder"]
        zone = ZoneInfo(saved(state)["timezone"])
        return {"jobs": list(search_reminders(jobs, query, zone)),
                "delivered": list(search_reminders(reversed(delivered), query, zone)),
                "outbox": list(search_reminders(reversed(outbox), query, zone, outbox=True)),
                "timezone": zone.key}

    def save(self, body):
        selection = settings(body)
        with self.storage.lock():
            state = self.storage.load()
            previous = saved(state)["timezone"]
            state["reminder_settings"] = selection
            if selection["timezone"] != previous:
                from . import goals
                goals.reschedule_timezone(state, datetime.now(timezone.utc))
            self.storage.save(state)
        return self.info()

    def token(self, item, operation, expires):
        payload = f"{item['id']}.{operation}.{expires}"
        return f"{payload}.{hmac.new(self.signing_key, payload.encode(), hashlib.sha256).hexdigest()}"

    def use_token(self, token, *, apply=False, clock=None):
        now = clock or datetime.now(timezone.utc)
        match = TOKEN.fullmatch(token) if isinstance(token, str) and len(token) < 140 else None
        if not match:
            raise HearthError("This reminder link is invalid.")
        identity, operation, expires, _ = match.groups()
        if not equal(token, self.token({"id": identity}, operation, expires)):
            raise HearthError("This reminder link is invalid.")
        with self.storage.lock():
            state = self.storage.load()
            item = next((item for item in scheduler.email_records(state) if item["id"] == identity), None)
            if not item or item.get("delivery", {}).get("email", {}).get("status") not in {"sent", "failed"}:
                raise HearthError("This reminder link is unavailable.")
            email = item["delivery"]["email"]
            if email["status"] == "failed" and not email.get("outbox"):
                raise HearthError("This reminder link is unavailable.")
            if now.timestamp() >= int(expires):
                raise HearthError("This reminder link expired.")
            if item.get("action"):
                return {"label": item["action"]["label"], "applied": True}
            if apply:
                action = change_occurrence(state, item, operation, now)
                self.storage.save(state)
                return {"label": action["label"], "applied": True}
            return {"label": ACTIONS[operation], "title": item["message"], "applied": False}

    def cancel(self, identity):
        with self.storage.lock():
            state = self.storage.load()
            job = cancel(state, identity, datetime.now(timezone.utc))
            self.storage.save(state)
        return job

    def test(self, channel):
        if channel not in ("app", "email"):
            raise HearthError("Choose In app or Email.")
        now = datetime.now(timezone.utc)
        with self.storage.lock():
            state = self.storage.load()
            if any(item["channel"] == channel and datetime.fromisoformat(item["delivered_at"]) >
                   now - timedelta(seconds=10) for item in state.get("reminder_tests", [])):
                raise HearthError("A test was just queued. Check Reminders for the result.")
            item = scheduler.occurrence({"id": new_id(), "message": "Hearth reminder test",
                                         "note": "This is a test of your reminder settings.", "urgent": True,
                                         "next_at": iso(now), "channel": channel}, now, test=True)
            state.setdefault("reminder_tests", []).append(item)
            log(state, f"Test reminder · {'In app sent' if channel == 'app' else 'Email queued'}", item, now)
            scheduler.next_due(state)
            self.storage.save(state)
        self.deliver(now, wait=True)
        with self.storage.lock():
            return public_item(next(row for row in self.storage.load()["reminder_tests"] if row["id"] == item["id"]))

    def email_payload(self, item, email):
        target = email["target"]
        return render_email(item, target["recipient"], target["base"], target["timezone"],
                            lambda operation: self.token(item, operation, target["expires"]))

    def outbox(self, identity):
        with self.storage.lock():
            state = self.storage.load()
        item = next((item for item in scheduler.email_records(state) if item["id"] == identity), None)
        if not item or not (email := item.get("delivery", {}).get("email", {})).get("outbox"):
            raise HearthError("This Outbox email does not exist.")
        return self.email_payload(item, email)

    def kick(self):
        if not self.worker.acquire(blocking=False):
            return
        thread = threading.Thread(target=self.work, name="hearth-reminder-delivery", daemon=True)
        try:
            thread.start()
        except RuntimeError:
            self.worker.release()
            raise

    def work(self):
        try:
            self.deliver()
        except (HearthError, OSError):
            # An interrupted send remains recoverable from its journal entry.
            pass
        finally:
            self.worker.release()

    def deliver(self, clock=None, *, wait=False):
        with self.exclusive("reminder-delivery", wait=wait) as acquired:
            if not acquired:
                return
            with scheduler.claims(self.storage) as allowed:
                if not allowed:
                    return
                with self.storage.lock():
                    self.reconcile_locked(unfinished=True)
            now = clock or datetime.now(timezone.utc)
            for _ in range(12):
                if not self.deliver_one(now):
                    break

    def deliver_one(self, now):
        config = dict(self.config())
        with scheduler.claims(self.storage) as allowed:
            if not allowed:
                return False
            with self.storage.lock():
                state = self.storage.load()
                item = next((item for item in scheduler.email_records(state) if scheduler.due_email(item, now)), None)
                if not item:
                    return False
                claimed = self.claim_email(state, item, config, now)
                scheduler.next_due(state)
                self.storage.save(state)
        if claimed:
            self.send_email(item, config, now)
        return True

    def claim_email(self, state, item, config, now):
        selection = saved(state)
        if scheduler.hold_email(state, item, now, selection):
            return False
        email = item["delivery"]["email"]
        email["target"] = email.get("target") or {
            "recipient": selection["recipient"], "timezone": selection["timezone"],
            "base": self.base, "connection": config.get("connection_id"),
            "inbox_setting": config.get("inbox_id", ""), "expires": int((now + LIFETIME).timestamp()),
        }
        email["actual_late"] = email.get("actual_late", max(
            item["late_minutes"], int((now - datetime.fromisoformat(item["scheduled_at"])).total_seconds() // 60)))
        if not config.get("connection_id") and not email["attempts"]:
            email.update(status="failed", reason=NOT_CONNECTED, outbox=True)
            state["outbox"].append({"id": item["id"], "kind": "reminder", "created_at": iso(now),
                                    "subject": f"Hearth reminder: {item['message']}", "reason": NOT_CONNECTED})
            log(state, f"Email failed · Saved to Outbox · {item['message']}", item, now, provider="agentmail",
                error=True, data={"reminder_id": item["id"], "status": "failed", "reason": NOT_CONNECTED})
            return False
        if (email.get("first_attempt_at") and
                datetime.fromisoformat(email["first_attempt_at"]) < now - timedelta(hours=22)):
            reason = "The AgentMail retry window expired. Check for prior delivery before sending again."
            email.pop("pending_reconcile", None)
            email.pop("claim_id", None)
            email.update(status="failed", reason=reason, uncertain=True)
            rows = delivery_journal.load(self.storage)
            row = delivery_journal.record(rows, item, email, event_at=now)
            delivery_journal.save(self.storage, rows)
            delivery_journal.project(state, item, row, set())
            return False
        if not email["target"]["recipient"] or not email["target"]["base"]:
            reason = ("Set a recipient in Settings → Reminders." if not email["target"]["recipient"]
                      else "Configure the private Hearth URL for email links.")
            email.update(status="failed", reason=reason)
            log(state, f"Email failed · {item['message']}", item, now, provider="agentmail", error=True,
                data={"reminder_id": item["id"], "status": "failed", "reason": reason})
            return False
        email["first_attempt_at"] = email.get("first_attempt_at") or iso(now)
        email.update(sending=True, pending_reconcile=True, claim_id=new_id(),
                     next_at=iso(now + timedelta(seconds=60)), reason="Sending reminder",
                     attempts=email["attempts"] + 1)
        rows = delivery_journal.load(self.storage)
        row = delivery_journal.record(rows, item, email)
        delivery_journal.save(self.storage, rows)
        email["receipt_revision"] = row["revision"]
        return True

    def prepare_send(self, item, email, inbox):
        # Pin the mailbox before the first provider send so an identical retry uses the same endpoint.
        with scheduler.claims(self.storage) as allowed:
            if allowed:
                with self.storage.lock():
                    rows = delivery_journal.load(self.storage)
                    saved_email = rows[delivery_journal.key(item)]["email"]
                    if saved_email.get("sending") and saved_email["claim_id"] == email["claim_id"]:
                        if not saved_email.get("send_inbox"):
                            saved_email["send_inbox"] = {"id": inbox["id"], "key": inbox["key"]}
                            delivery_journal.save(self.storage, rows)
                        return
        raise ConnectorError("Reminder delivery was paused for reconciliation.", 504)

    def send_email(self, item, config, now):
        email = item["delivery"]["email"]
        deadline = time.monotonic() + DELIVERY_TIMEOUT
        timer = threading.Timer(DELIVERY_TIMEOUT, self.expire_send, args=(item, email["claim_id"]))
        timer.daemon = True
        timer.start()
        message_id, status = None, None
        retry_conflict = False
        try:
            target = email["target"]
            if not config.get("connection_id") or (config["connection_id"], config.get("inbox_id", "")) != (
                target["connection"], target["inbox_setting"]
            ):
                raise ConnectorError("AgentMail connection changed.", 409)
            client = AgentMail(self.app.gateway, config, deadline=deadline)
            inbox = email.get("send_inbox") or self.mailbox(client)
            payload = self.email_payload({**item, "late_minutes": email["actual_late"]}, email)
            payload["labels"] = ["hearth-reminder"]
            self.prepare_send(item, email, inbox)
            retry_conflict = email["attempts"] > 1 and email.get("uncertain")
            response = client.send(inbox, payload, f"hearth-reminder-{item['id']}")
            if not isinstance(response.get("message_id"), str) or not response["message_id"]:
                raise ConnectorError("AgentMail could not confirm delivery.")
            message_id = response["message_id"]
        except ConnectorError as error:
            status = error.status
        finally:
            timer.cancel()
        self.finish_email(item, email["claim_id"], now, message_id, status, retry_conflict)

    def expire_send(self, item, claim_id):
        # A blocked socket keeps its delivery lock until it returns. Preserve late receipts.
        try:
            with scheduler.claims(self.storage) as allowed:
                with self.storage.lock():
                    rows = delivery_journal.load(self.storage)
                    email = rows[delivery_journal.key(item)]["email"]
                    if not email.get("sending") or email["claim_id"] != claim_id:
                        return
                    delivery_journal.mark_unfinished(rows)
                    delivery_journal.save(self.storage, rows)
                    if allowed:
                        self.project_delivery(rows)
        except OSError:
            pass

    def finish_email(self, item, claim_id, now, message_id, status, retry_conflict):
        with scheduler.claims(self.storage) as allowed:
            with self.storage.lock():
                rows = delivery_journal.load(self.storage)
                email = rows[delivery_journal.key(item)]["email"]
                if email.get("claim_id") != claim_id:
                    return
                email.pop("claim_id")
                email.pop("sending", None)
                email.pop("pending_reconcile", None)
                if message_id:
                    email.pop("uncertain", None)
                    email.update(status="sent", at=iso(now), reason="", message_id=message_id,
                                 mailbox=email.pop("send_inbox")["key"])
                else:
                    transient = (status is None or status in (408, 429) or status >= 500
                                 or status == 409 and retry_conflict)
                    reason = f"AgentMail returned HTTP {status}." if status else "AgentMail could not confirm delivery."
                    email["uncertain"] = email.get("uncertain", False) or transient and status != 429 or status == 409
                    if transient and email["attempts"] <= len(BACKOFF):
                        email.update(status="queued", next_at=iso(now + timedelta(seconds=BACKOFF[email["attempts"] - 1])),
                                     reason=f"{reason} Retrying with backoff.")
                        if email["uncertain"]:
                            email["pending_reconcile"] = True
                    else:
                        email.update(status="failed", reason=reason)
                # Persist this outcome even if a restore erased the live occurrence.
                delivery_journal.record(rows, item, email, event_at=now)
                delivery_journal.save(self.storage, rows)
                if allowed:
                    self.project_delivery(rows)

    def project_delivery(self, rows):
        state = self.storage.load()
        if scheduler.reconcile(state, rows)[0]:
            scheduler.next_due(state)
            self.storage.save(state)
