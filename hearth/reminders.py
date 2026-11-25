import fcntl
import hashlib
import hmac
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from . import scheduler, timeline
from .agentmail import AgentMail
from .connectors import ConnectorError
from .reminder_config import CHANNELS, NOT_CONNECTED, equal, public_url, quiet_until, saved, secret, settings
from .scheduler import can_cancel, pending_occurrences
from .storage import HearthError, iso, new_id
from .threads import MAIN_ORIGIN

ACTIONS = {"done": "Done", "snooze-10": "Snooze 10 min", "snooze-60": "Snooze 1 h"}
TOKEN = re.compile(r"([a-f0-9]{32})\.(done|snooze-10|snooze-60)\.(\d{1,12})\.([a-f0-9]{64})")
LIFETIME = timedelta(days=7)
BACKOFF = (60, 300, 1800, 7200)


def log(state, title, origin, now, *, data=None, provider=None, error=False):
    state.setdefault("activity", []).append(timeline.entry(
        "reminder", title, origin, id=new_id(), at=iso(now), data=data or {}, provider=provider, error=error))


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
                          origin={key: item[key] for key in MAIN_ORIGIN})["snoozed_at"] = iso(now)
        label = f"Snoozed {minutes} min"
    item["action"] = {"label": label, "at": iso(now)}
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


class Reminders:
    def __init__(self, app):
        self.app = app
        self.storage = app.storage
        self.tick_token = secret(self.storage, "scheduler-tick.token")
        self.signing_key = secret(self.storage, "reminder-action.key").encode()
        self.base = public_url(os.environ.get("HEARTH_PUBLIC_URL"))

    def config(self):
        return self.app.agent.config.get("agentmail", {})

    def client(self):
        config = self.config()
        if not config.get("connection_id"):
            raise HearthError(NOT_CONNECTED)
        return AgentMail(self.app.gateway, config)

    @contextmanager
    def exclusive(self, name, *, wait=False):
        with (self.storage.root / f"{name}.lock").open("a") as file:
            try:
                fcntl.flock(file, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                yield False
            else:
                yield True

    def mailbox(self, client):
        config = client.config
        key = f"{config['connection_id']}:{config.get('inbox_id', '')}"
        with self.exclusive("agentmail-inbox", wait=True):
            with self.storage.lock():
                old = self.storage.load().get("agentmail_inbox", {})
            if old.get("key") == key:
                return old
            inbox = {**client.ensure_inbox(), "key": key}
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

    def list(self):
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
        return {"jobs": jobs, "delivered": delivered[::-1], "outbox": outbox[::-1],
                "timezone": saved(state)["timezone"]}

    def save(self, body):
        selection = settings(body)
        with self.storage.lock():
            state = self.storage.load()
            state["reminder_settings"] = selection
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

    def deliver(self, clock=None, *, wait=False):
        with self.exclusive("reminder-delivery", wait=wait) as acquired:
            if not acquired:
                return
            now = clock or datetime.now(timezone.utc)
            for _ in range(12):
                if not self.deliver_one(now):
                    break

    def deliver_one(self, now):
        config = self.config()
        connected = bool(config.get("connection_id"))
        with self.storage.lock():
            state = self.storage.load()
            selection = saved(state)
            item = next((item for item in scheduler.email_records(state) if
                         (email := item.get("delivery", {}).get("email")) and email["status"] == "queued"
                         and datetime.fromisoformat(email["next_at"]) <= now), None)
            if not item:
                return False
            email = item["delivery"]["email"]
            # Once a send may have reached AgentMail, keep its original payload and key for retries.
            held = None if item["urgent"] or email.get("attempts") else quiet_until(now, selection)
            if held:
                email.update(next_at=iso(held), reason="Quiet hours")
                log(state, "Email queued · Quiet hours", item, now, provider="agentmail",
                    data={"reminder_id": item["id"], "next_due": iso(held), "status": "queued"})
            else:
                email["target"] = email.get("target") or {
                    "recipient": selection["recipient"], "timezone": selection["timezone"],
                    "base": self.base, "connection": config.get("connection_id"),
                    "inbox_setting": config.get("inbox_id", ""),
                    "expires": int((now + LIFETIME).timestamp()),
                }
                email["actual_late"] = email.get("actual_late", max(
                    item["late_minutes"], int((now - datetime.fromisoformat(item["scheduled_at"])).total_seconds() // 60)))
                if not connected and not email["attempts"]:
                    email.update(status="failed", reason=NOT_CONNECTED, outbox=True)
                    state["outbox"].append({"id": item["id"], "kind": "reminder", "created_at": iso(now),
                                            "subject": f"Hearth reminder: {item['message']}", "reason": NOT_CONNECTED})
                    log(state, f"Email failed · Saved to Outbox · {item['message']}", item, now, provider="agentmail",
                        error=True, data={"reminder_id": item["id"], "status": "failed", "reason": NOT_CONNECTED})
                elif (email.get("first_attempt_at") and
                      datetime.fromisoformat(email["first_attempt_at"]) < now - timedelta(hours=22)):
                    reason = "The AgentMail retry window expired. Check for prior delivery before sending again."
                    email.pop("sending", None)
                    email.update(status="failed", reason=reason, uncertain=True)
                    log(state, f"Email failed · {item['message']}", item, now, provider="agentmail", error=True,
                        data={"reminder_id": item["id"], "status": "failed", "reason": reason})
                elif not email["target"]["recipient"] or not email["target"]["base"]:
                    reason = ("Set a recipient in Settings → Reminders." if not email["target"]["recipient"]
                              else "Configure the private Hearth URL for email links.")
                    email.update(status="failed", reason=reason)
                    log(state, f"Email failed · {item['message']}", item, now, provider="agentmail", error=True,
                        data={"reminder_id": item["id"], "status": "failed", "reason": reason})
                else:
                    email["first_attempt_at"] = email.get("first_attempt_at") or iso(now)
                    email.update(sending=True, next_at=iso(now + timedelta(seconds=60)), reason="Sending reminder",
                                 attempts=email["attempts"] + 1)
            scheduler.next_due(state)
            self.storage.save(state)
            if not email.get("sending") or held:
                return True
        try:
            if not connected or (config.get("connection_id"), config.get("inbox_id", "")) != (
                email["target"]["connection"], email["target"]["inbox_setting"]
            ):
                raise ConnectorError("AgentMail connection changed.", 409)
            client = self.client()
            inbox = self.mailbox(client)
            payload = self.email_payload({**item, "late_minutes": email["actual_late"]}, email)
            payload["labels"] = ["hearth-reminder"]
            response = client.send(inbox, payload, f"hearth-reminder-{item['id']}")
            if not isinstance(response.get("message_id"), str) or not response["message_id"]:
                raise ConnectorError("AgentMail could not confirm delivery.")
        except ConnectorError as error:
            response = None
            status = error.status
            transient = status is None or status in (408, 429) or status >= 500
            reason = f"AgentMail returned HTTP {status}." if status else "AgentMail could not confirm delivery."
        with self.storage.lock():
            state = self.storage.load()
            current = next((row for row in scheduler.email_records(state) if row["id"] == item["id"]), None)
            if not current:
                return True
            email = current["delivery"]["email"]
            email.pop("sending", None)
            if response is not None:
                email.update(status="sent", at=iso(now), reason="", message_id=response["message_id"], mailbox=inbox["key"])
                current["late_minutes"] = max(current["late_minutes"], email["actual_late"])
            else:
                email["uncertain"] = email.get("uncertain", False) or transient and status != 429 or status == 409
                if transient and email["attempts"] <= len(BACKOFF):
                    email.update(status="queued", next_at=iso(now + timedelta(seconds=BACKOFF[email["attempts"] - 1])),
                                 reason=f"{reason} Retrying with backoff.")
                else:
                    email.update(status="failed", reason=reason)
            log(state, f"Email {email['status']} · {current['message']}", current, now, provider="agentmail",
                error=email["status"] == "failed",
                data={"reminder_id": item["id"], "delivery": public_delivery({"email": email}),
                      "late_minutes": current["late_minutes"]})
            scheduler.next_due(state)
            self.storage.save(state)
        return True
