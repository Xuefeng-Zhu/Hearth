import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from zoneinfo import ZoneInfo

from . import approvals, artifacts, mail_content, office, scheduler, tasks, timeline
from .connectors import ConnectorError
from .reminder_config import KINDS, NOT_CONNECTED, saved
from .reminders import cancel, change_occurrence
from .scheduler import can_cancel
from .storage import HearthError, iso, new_id
from .threads import MAIN_ORIGIN

ORIGIN = {**MAIN_ORIGIN, "source": "email"}
COMMAND = re.compile(r"(done[.!]?|snooze[ \t]+([1-9]\d{0,3})(?:[ \t]*(?:m|min|minutes?))?[.!]?)", re.I)


def identity(inbox, message):
    return hashlib.sha256(f"{inbox['id']}\0{message}".encode()).hexdigest()


def activity(state, card, title, now, *, error=False, **fields):
    entry = timeline.entry("inbox", title, ORIGIN, id=new_id(), at=iso(now), provider="agentmail", error=error,
                           data={"inbox_id": card["id"], "proposal": card["proposal"]["kind"],
                                 "status": card["status"], **fields})
    state.setdefault("activity", []).append(entry)
    return entry


def trusted_sender(message, selection):
    labels = message.get("labels", [])
    auth = message.get("authentication_results") or {}
    return (mail_content.sender(message.get("from")) in selection["allowed_senders"] and isinstance(auth, dict)
            and auth.get("dmarc") == "pass" and not {"unauthenticated", "agent-armor-held"} & set(labels))


def public(card):
    return {key: value for key, value in card.items()
            if key not in {"message_id", "mailbox", "changes", "acknowledge", "fallback"}}


def times_for(proposal, now):
    kind = proposal["kind"]
    events = proposal["events"] or [{"title": proposal["title"], "at": proposal["at"]}]
    for event in events:
        date = mail_content.parse_date(event["at"], timezone.utc)
        if not date or date <= now:
            continue
        if kind == "event":
            lead = timedelta(hours=2 if re.search(r"\bflight\b|航班", proposal["title"], re.I) else 1)
            due = max(date - lead, now + timedelta(minutes=1))
            if due >= date:
                continue
        else:
            due = date
        title = f"Return deadline · {event['title']}" if kind == "receipt" else event["title"]
        yield title, due


class Inbox:
    def __init__(self, app):
        self.app = app
        self.storage = app.storage
        self.reminders = app.reminders

    def list(self):
        with self.storage.lock():
            state = self.storage.load()
            cards = state.get("inbox", {}).values()
            entries = sorted((public(card) for card in cards), key=lambda card: card["received_at"], reverse=True)
        now = datetime.now(timezone.utc)
        return {"cards": entries, "task_notifications": tasks.inbox_rows(state, now),
                "approvals": approvals.records(self.storage, clock=now), **self.reminders.info()}

    def poll(self, *, force=False, manual=False, clock=None):
        now = clock or datetime.now(timezone.utc)
        if not self.reminders.config().get("connection_id"):
            if manual:
                raise HearthError(NOT_CONNECTED)
            return 0
        with self.reminders.exclusive("inbox-poll", wait=manual) as acquired:
            if not acquired:
                return 0
            with self.storage.lock():
                state = self.storage.load()
                last = state.get("inbox_poll", {}).get("at")
                if not force and last and datetime.fromisoformat(last) > now - timedelta(seconds=55):
                    return 0
            try:
                client = self.reminders.client()
                mailbox = self.reminders.mailbox(client)
                count = self.read_page(client, mailbox, now)
                self.acknowledge(client, mailbox, now)
                error, transient = None, False
            except (ConnectorError, HearthError) as exc:
                status = getattr(exc, "status", None)
                transient = status is None or status in (408, 429) or status >= 500
                error = f"AgentMail returned HTTP {status}." if status else "Hearth could not check the AgentMail inbox."
                count = 0
            with self.storage.lock():
                state = self.storage.load()
                previous = state.get("inbox_poll", {})
                same_error = error and error == previous.get("error")
                failures = (previous.get("failures", 1) + 1 if same_error else 1) if error else 0
                actionable = bool(error) and (not transient or failures >= 3)
                incident = previous.get("incident") if same_error else None
                if actionable and not incident:
                    incident = new_id()
                    state.setdefault("activity", []).append(timeline.entry(
                        "inbox", "AgentMail inbox poll failed", ORIGIN, id=incident, at=iso(now),
                        provider="agentmail", error=True, data={"reason": error}))
                state["inbox_poll"] = {"at": iso(now), "error": error, "failures": failures, "incident": incident}
                self.storage.save(state)
            if manual and error:
                raise HearthError(error)
            return count

    def read_page(self, client, mailbox, now):
        with self.storage.lock():
            state = self.storage.load()
            cursor = state.get("inbox_cursors", {}).get(mailbox["key"], {})
        after = cursor.get("after")
        token = cursor.get("page")
        try:
            page = client.page(mailbox, after, token)
        except ConnectorError as error:
            if not token or error.status not in (400, 404, 410, 422):
                raise
            page = client.page(mailbox, after, None)
        if not isinstance(page.get("messages"), list):
            raise ConnectorError("AgentMail returned an unreadable message list.")
        watermark = cursor.get("watermark")
        handled = 0
        for item in page["messages"]:
            message_id = item.get("message_id") if isinstance(item, dict) else None
            if not isinstance(message_id, str) or not 0 < len(message_id) <= 512:
                continue
            at = mail_content.parse_date(item.get("timestamp"), timezone.utc)
            if at and at <= now and (not watermark or at > datetime.fromisoformat(watermark)):
                watermark = at.isoformat()
            card_id = identity(mailbox, message_id)
            with self.storage.lock():
                state = self.storage.load()
                if card_id in state.get("inbox", {}) or card_id in state.get("inbox_handled", {}):
                    continue
                selection = saved(state)
            try:
                if isinstance(item.get("text"), str) or isinstance(item.get("html"), str):
                    message = item
                else:
                    message = {**item, **client.message(mailbox, message_id)}
            except ConnectorError as error:
                if error.status == 404:
                    continue
                raise
            handled += self.process(client, mailbox, card_id, message_id, message, selection, now)
        next_page = page.get("next_page_token")
        if not next_page and watermark:
            after = (datetime.fromisoformat(watermark) - timedelta(minutes=10)).isoformat()
        with self.storage.lock():
            state = self.storage.load()
            state.setdefault("inbox_cursors", {})[mailbox["key"]] = {
                "after": after, "page": next_page, "watermark": watermark}
            self.storage.save(state)
        return handled

    def process(self, client, mailbox, card_id, message_id, message, selection, now):
        sender = mail_content.sender(message.get("from"))
        labels = set(message.get("labels", []))
        recipients = message.get("to") or []
        own_sender = sender == mailbox["address"]
        addressed_here = mailbox["address"] in map(mail_content.sender, recipients)
        if (own_sender and not addressed_here) or labels.intersection(
                {"spam", "blocked", "agent-armor-held", "agent-armor-pending", "hearth-reminder", "hearth-ack"}):
            self.mark_handled(card_id, now)
            return 0
        verified = trusted_sender(message, selection) and not own_sender
        if verified and self.apply_reply(card_id, mailbox, message, sender, now):
            return 1
        zone = ZoneInfo(selection["timezone"])
        forwarded = mail_content.strip_forward(message, zone)
        contains_instructions = bool(mail_content.INJECTION.search(f"{forwarded['title']}\n{mail_content.plain(message)}"))
        files, events = self.attachments(client, mailbox, message_id, message.get("attachments"), zone)
        contains_instructions |= any(mail_content.INJECTION.search(file.get("text", "")) for file in files)
        received = mail_content.parse_date(message.get("created_at") or message.get("timestamp"), zone) or now
        reference = mail_content.parse_date(forwarded["original_date"], zone) or received
        fallback = mail_content.classify({**forwarded, "sender": sender}, zone, reference, events)
        proposal = fallback
        if verified and not contains_instructions:
            agent = self.app.agent
            model = next((model for model in agent.models if (model["provider"], model["model"]) == self.app.brain_reply),
                         agent.models[0])
            proposal = mail_content.brain_classify(self.app.gateway, model, forwarded, fallback, zone, reference)
        card = {"id": card_id, "message_id": message_id, "mailbox": mailbox["key"], "sender": sender,
                **forwarded, "received_at": iso(received), "allowlisted": sender in selection["allowed_senders"],
                "authenticated": verified, "suspicious": contains_instructions, "attachments": files,
                "proposal": proposal, "fallback": fallback, "status": "review"}
        with self.storage.lock():
            state = self.storage.load()
            cards = state.setdefault("inbox", {})
            if card_id in cards:
                return 0
            cards[card_id] = card
            activity(state, card, f"Email received · {card['title']}", now, summary=proposal["summary"])
            current = saved(state)
            if (verified and sender in current["allowed_senders"] and not contains_instructions and
                    proposal["kind"] in current["auto_accept"] and fallback["kind"] == proposal["kind"] and
                    fallback["at"] == proposal["at"] and
                    (proposal["kind"] not in {"reminder", "event"} or
                     mail_content.parse_date(proposal["at"], zone) and datetime.fromisoformat(proposal["at"]) > now)):
                self.accept(state, card, fallback, now, automatic=True)
            self.storage.save(state)
        if card["status"] == "accepted":
            self.app.memory_sync.request()
        return 1

    def attachments(self, client, mailbox, message_id, items, zone):
        files, events = [], []
        for item in (items[:15] if isinstance(items, list) else []):
            if not isinstance(item, dict):
                continue
            name = mail_content.clean(item.get("filename"), 180) or "Attachment"
            mime = mail_content.clean(item.get("content_type"), 100)
            size = item.get("size")
            attachment = {"name": name, "type": mime, "size": size if type(size) is int else None}
            files.append(attachment)
            cid = item.get("attachment_id")
            ext = name.lower().rsplit(".", 1)[-1]
            calendar = ext == "ics" or mime.startswith("text/calendar")
            pdf = ext == "pdf" or mime.startswith("application/pdf")
            textish = calendar or pdf or ext in {"txt", "csv"} or mime.startswith(("text/plain", "text/csv"))
            if textish and isinstance(cid, str) and len(cid) <= 512 and len(files) <= 5:
                try:
                    content = client.attachment(mailbox, message_id, cid, pdf=pdf)
                    if calendar:
                        events.extend(mail_content.parse_ics(content, zone))
                    attachment["text"] = mail_content.clean(content)
                except (ConnectorError, HearthError, URLError, ValueError, OSError):
                    attachment["note"] = "Text unavailable"
        return files, events[:10]

    def apply_reply(self, card_id, mailbox, message, sender, now):
        reference = message.get("in_reply_to")
        line = mail_content.plain(message, extracted=True).splitlines()
        command = COMMAND.fullmatch(line[0].strip()) if line else None
        if not reference or not command or mail_content.INJECTION.search(mail_content.plain(message, extracted=True)):
            return False
        minutes = int(command[2]) if command[2] else 0
        if minutes > 1440:
            return False
        with self.storage.lock():
            state = self.storage.load()
            if not trusted_sender(message, saved(state)):
                return False
            for item in scheduler.email_records(state):
                email = item.get("delivery", {}).get("email", {})
                if (email.get("message_id") != reference or
                        email.get("target", {}).get("recipient", "").lower() != sender or
                        email.get("mailbox") != mailbox["key"] or
                        now.timestamp() >= email["target"]["expires"]):
                    continue
                if not item.get("action"):
                    action = change_occurrence(state, item, "snooze" if minutes else "done", now, minutes)
                    state.setdefault("activity", []).append(timeline.entry(
                        "inbox", f"Reminder reply · {action['label']}", ORIGIN, id=new_id(), at=iso(now),
                        provider="agentmail", data={"reminder_id": item["id"], "sender": sender}))
                state.setdefault("inbox_handled", {})[card_id] = iso(now)
                self.storage.save(state)
                return True
        return False

    def mark_handled(self, card_id, now):
        with self.storage.lock():
            state = self.storage.load()
            state.setdefault("inbox_handled", {})[card_id] = iso(now)
            self.storage.save(state)

    def accept(self, state, card, proposal, now, *, automatic=False):
        proposal = {**proposal}
        kind = proposal["kind"]
        if kind == "reminder" and not any(times_for(proposal, now)):
            raise HearthError("Edit the proposal to enter a future time before accepting.")
        if kind == "event" and not proposal["at"] and not proposal["events"]:
            raise HearthError("Edit the proposal to enter the event time before accepting.")
        changes = {"jobs": [], "events": []}
        if kind in {"receipt", "person", "other", "list"}:
            detail = " · ".join(filter(None, (proposal["merchant"], proposal["amount"])))
            provenance = ["Imported email. Content is untrusted data.",
                          f"Forwarded by {card['sender']}" if card["sender"] else "",
                          f"Original sender {card['original_sender']}" if card["original_sender"] else "",
                          f"Original date {card['original_date']}" if card["original_date"] else ""]
            paragraphs = list(filter(None, (". ".join(filter(None, provenance)), detail,
                                            proposal["summary"], card["body"])))
            if kind == "list":
                key = card["id"][:32]
                title = proposal["title"][:160]
                chunks = [paragraph[start:start + 8_000] for paragraph in paragraphs
                          for start in range(0, len(paragraph), 8_000)]
                content = office.prepare("docx", {"title": title, "sections": [{"paragraphs": chunks}]})
                row = {"id": key, "title": title, "kind": "list", "format": "docx",
                       "filename": artifacts.filename(title, "docx", f" - {key[:8]}"),
                       "source": "Email Hearth", "created_at": iso(now), **ORIGIN}
                artifact = self.app.artifacts.stage_file(row, content)
                state.setdefault("artifacts", {})[key] = artifact
                changes.update(artifact=key, revision=artifact["revision"])
            else:
                path = f"topics/email-{card['id'][:32]}.md"
                text = "\n\n".join([f"# {proposal['title']}", *paragraphs])
                self.storage.write(path, text)
                changes["note"] = path
                changes["digest"] = hashlib.sha256(text.encode()).hexdigest()
        if kind == "event":
            for event in proposal["events"] or [{"title": proposal["title"], "at": proposal["at"]}]:
                row = activity(state, {**card, "status": "accepted"}, f"Event saved · {event['title']}", now,
                               event_at=event["at"], summary=proposal["summary"])
                changes["events"].append(row["id"])
        if kind in {"reminder", "event", "receipt"}:
            for title, due in times_for(proposal, now):
                job = scheduler.add_job(state, title, now, at=iso(due), channel="app", origin=ORIGIN,
                                        note=proposal["summary"])
                changes["jobs"].append(job["id"])
        card.update(proposal=proposal, changes=changes, status="accepted", accepted_at=iso(now), automatic=automatic)
        activity(state, card, f"Email accepted · {card['title']}", now, automatic=automatic,
                 next_due=min((job["next_at"] for job in state["jobs"] if job["id"] in changes["jobs"]), default=None))
        selection = saved(state)
        if (selection["acknowledge"] and not card["suspicious"] and card["authenticated"]
                and card["sender"] in selection["allowed_senders"] and not card.get("acknowledged_at")):
            first_due = min((job["next_at"] for job in state["jobs"] if job["id"] in changes["jobs"]), default=None)
            when = (datetime.fromisoformat(first_due).astimezone(ZoneInfo(selection["timezone"])).strftime(
                "%a, %b %d at %I:%M %p %Z") if first_due else None)
            card["acknowledge"] = {"text": f"Got it — reminder set for {when}." if when else "Got it — saved in Hearth.",
                                   "created_at": iso(now)}

    def acknowledge(self, client, mailbox, now):
        with self.storage.lock():
            state = self.storage.load()
            pending = [card["id"] for card in state.get("inbox", {}).values()
                       if card.get("acknowledge") and card["mailbox"] == mailbox["key"]]
        for key in pending[:5]:
            with self.storage.lock():
                state = self.storage.load()
                card = state.get("inbox", {}).get(key, {})
                if not card.get("acknowledge"):
                    continue
                selection = saved(state)
                if not selection["acknowledge"] or card["sender"] not in selection["allowed_senders"]:
                    card.pop("acknowledge")
                    self.storage.save(state)
                    continue
                ack = card["acknowledge"]
                if approvals.needs_approval(state, ("send",)):
                    subject = f"Re: {card['title']}"
                    sender = card["sender"]
                    row = approvals.proposal(state, "email_acknowledgment",
                                             {"to": sender, "text": ack["text"], "inbox": mailbox["id"],
                                              "message_id": card["message_id"]}, ("send",), ORIGIN,
                                             {"kind": "email", "title": "Reply to forwarded email", "target": sender,
                                              "recipients": [sender], "binding": self.app.agent.gateway_target(client.config),
                                              "email": {"to": [sender], "subject": subject, "text": ack["text"]},
                                              "editable": {"text": ack["text"]}, "mocked": False}, now=now, dedupe=key)
                    card.pop("acknowledge")
                    self.storage.save(state)
                    self.app.threads.append("main", "assistant", "Review this email reply.", action_ids=[row["id"]])
                    continue
            try:
                if datetime.fromisoformat(ack["created_at"]) < now - timedelta(hours=22):
                    raise ConnectorError("Acknowledgment expired.", 410)
                result = client.reply(mailbox, card["message_id"], card["sender"], ack["text"], f"hearth-ack-{key}")
                if not result.get("message_id"):
                    raise ConnectorError("AgentMail could not confirm acknowledgment.")
            except ConnectorError as error:
                if error.status is None or error.status in (408, 429) or error.status >= 500:
                    continue
                reason = f"AgentMail returned HTTP {error.status}."
            else:
                reason = None
            with self.storage.lock():
                state = self.storage.load()
                current = state.get("inbox", {}).get(key)
                if current:
                    current.pop("acknowledge", None)
                    current["acknowledged_at"] = iso(now) if reason is None else None
                    activity(state, current, "Email acknowledgment failed" if reason else "Email acknowledgment sent",
                             now, error=bool(reason), reason=reason)
                    self.storage.save(state)

    def update(self, operation, body):
        key = body.get("id")
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise HearthError("Choose an Inbox card.")
        now = datetime.now(timezone.utc)
        with self.storage.lock():
            state = self.storage.load()
            card = state.get("inbox", {}).get(key)
            if not card:
                raise HearthError("This Inbox card does not exist.")
            if operation == "undo" and card["status"] == "accepted":
                self.undo(state, card, now)
            elif card["status"] != "review":
                return public(card)
            elif operation == "dismiss":
                card["status"] = "dismissed"
                activity(state, card, f"Email dismissed · {card['title']}", now)
            elif operation in ("accept", "edit"):
                proposal = dict(card["proposal"])
                if operation == "edit":
                    title = mail_content.clean(body.get("title"), 240)
                    summary = mail_content.clean(body.get("summary"), 2_000)
                    kind = body.get("kind")
                    at = body.get("at")
                    if not title or kind not in KINDS or (at is not None and (
                        not isinstance(at, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)", at)
                        or not mail_content.parse_date(at, timezone.utc))):
                        raise HearthError("Provide a title, proposal type, and a valid date if scheduled.")
                    original_at = proposal["at"]
                    proposal.update(title=title, summary=summary, kind=kind, at=at)
                    if kind != "event" or original_at != at:
                        proposal["events"] = []
                self.accept(state, card, proposal, now)
            else:
                raise HearthError("Choose Accept, Edit, Dismiss, or Undo.")
            self.storage.save(state)
        if operation in {"accept", "edit", "undo"}:
            self.app.memory_sync.request()
        return public(card)

    def undo(self, state, card, now):
        changes = card["changes"]
        artifact = state.get("artifacts", {}).get(changes.get("artifact"))
        path = self.storage.memory_path(changes["note"]) if changes.get("note") else None
        jobs = [job for job in state["jobs"] if job["id"] in changes["jobs"]]
        if artifact and artifact.get("revision") != changes["revision"]:
            raise HearthError("This artifact has newer edits. Undo them before removing the import.")
        if path and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() != changes["digest"]:
            raise HearthError("This note has newer edits. Undo them before removing the import.")
        if any(not can_cancel(state, job) and job.get("status") == "scheduled" for job in jobs):
            raise HearthError("An upcoming reminder is already being sent.")
        if artifact:
            del state["artifacts"][artifact["id"]]
        if path:
            path.unlink(missing_ok=True)
        for job in jobs:
            if can_cancel(state, job):
                cancel(state, job["id"], now)
        for entry in state.get("activity", []):
            if entry["id"] in changes["events"]:
                entry.update(undone=True, undone_at=iso(now))
        card.update(status="undone", undone_at=iso(now))
        card.pop("acknowledge", None)
        activity(state, card, f"Email acceptance undone · {card['title']}", now)
