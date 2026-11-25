import threading
from contextlib import closing

from .connections import catalog_entry
from .gateway_tools import scrub
from .scheduler import can_cancel, email_records
from .storage import iso, new_id
from .threads import MAIN_ORIGIN, compact


def connector_fields(provider):
    return {"provider": provider, "connector": catalog_entry(provider)["name"]} if provider and provider != "mock" else {}


def entry(kind, title, origin, **fields):
    return {"kind": kind, "title": title, **MAIN_ORIGIN,
            **{key: origin[key] for key in ("thread_id", "thread_title", "source") if key in origin},
            **fields, **connector_fields(fields.get("provider"))}


def record(storage, kind, title, origin, **fields):
    event = scrub(entry(kind, title, origin, id=new_id(), at=iso(), **fields))
    with storage.lock():
        state = storage.load()
        state.setdefault("activity", []).append(event)
        storage.save(state)


def pinecone_sync(row, target):
    if row["kind"] != "memory" or row.get("provider") != "pinecone":
        return False
    data = row["data"]
    index = target.get("name", target.get("index"))
    return (data.get("mode") in {"startup", "change", "sync", "rebuild"}
            and data.get("namespace") == target["namespace"]
            and data.get("index", index) == index)


def actionable(entries, state, pinecone, mail_connected):
    poll = state.get("inbox_poll", {}) if mail_connected else {}
    latest_sync = latest_poll = None
    for row in entries:
        if pinecone_sync(row, pinecone):
            latest_sync = row
        elif row["kind"] == "inbox" and row["title"] == "AgentMail inbox poll failed":
            latest_poll = row
    for row in entries:
        kind, title, data = row["kind"], row["title"], row["data"]
        is_pinecone = kind == "memory" and row.get("provider") == "pinecone" and data.get("mode")
        if is_pinecone and (data.get("retrying") or (
            data["mode"] == "startup" and data.get("status") == "complete" and data.get("work") == 0
        )):
            row["diagnostic"] = True
        if not row.get("error"):
            continue
        if row.get("undone") or (kind == "tool" and title != "Chat interrupted"):
            row["error"] = False
        elif kind in {"brain", "search"} and title in {"Brain fallback", "Search fallback"}:
            row["error"] = False
        elif is_pinecone:
            row["error"] = (row is latest_sync and pinecone["state"] == "Unavailable"
                            and not data.get("retrying"))
        elif kind == "inbox" and title == "AgentMail inbox poll failed":
            row["error"] = (row is latest_poll and data.get("reason") == poll.get("error")
                            and (poll.get("incident") == row["id"] if "incident" in poll else True))
        if not row["error"]:
            row["diagnostic"] = True


ERROR_STATUSES = {"changing", "partial", "unknown", "sending", "request_unknown", "failed"}


def action_entry(action, can_undo):
    kind, title = action["kind"], action["title"]
    status = action["status"]
    provider = action.get("provider")
    error = status in ERROR_STATUSES or kind in {"brain", "search"}
    if kind == "email":
        title = {"simulated": "Simulated email sent", "sent": "Email sent", "unknown": "Email delivery unconfirmed",
                 "sending": "Email delivery unconfirmed"}.get(status, title)
        title += f" · {action['email']['subject']}"
        if not action.get("mocked") and status != "pending":
            provider = "agentmail"
    elif kind == "gateway" and not action.get("tool"):
        request = action["request"]
        provider = request["provider"]
        title = f"{'Proposed' if status == 'pending' else 'Requested'} {request['method']} {request['path']}"
    elif kind == "reminder":
        title += f" · {action['job']['message']}"
    elif kind == "page":
        label = "Page created" if action["previous_version"] is None else "Page updated"
        title = f"{label} · {title.partition(' · ')[2]}"
    elif action.get("paths"):
        title += f" · {', '.join(action['paths'])}"
    elif kind == "remember" and status == "complete":
        title = f"Memory saved · {action['fact']}"
    if action.get("tool") and kind == "gateway":
        provider = action["request"]["provider"]
    return entry(kind, compact(title, 180), action, id=f"action:{action['id']}",
                 at=action.get("updated_at", action["at"]), provider=provider, model=action.get("model"),
                 error=error, action_id=action["id"], undoable=can_undo(action),
                 undone=bool(action.get("undone")), undone_at=action.get("undone_at"),
                 redoable=bool(action.get("undone") and action.get("memory_change")),
                 data={key: value for key, value in action.items() if key not in {"target", "response"}})


def chat_entries(threads, thread_list, logged_recall):
    for thread in thread_list:
        origin = {"thread_id": thread["id"], "thread_title": thread["title"]}
        pending = None
        for index, message in enumerate(threads.messages(thread["id"])):
            key = message.get("id") or f"{thread['id']}:{index}"
            source = {**origin, "source": message.get("source")}
            role = message["role"]
            if role == "call":
                yield entry("voice", message["content"], source, id=f"voice:{key}",
                            at=message["at"], provider=None if message.get("demo") else "vocalbridge", data=message)
            elif role == "user":
                if pending:
                    yield pending
                pending = entry("chat", compact(message["content"], 180) or "Chat message",
                                source, id=f"chat:{key}", at=message.get("at"),
                                data={"prompt": message["content"]})
                if message.get("shared_from"):
                    yield {**pending, "title": "Shared a message to Main"}
                    pending = None
            elif role == "assistant":
                route = message.get("routing") or {}
                turn = pending or entry("chat", "Hearth replied", source, id=f"chat:{key}", at=message.get("at"),
                                        data={})
                turn.update(at=message.get("at") or turn["at"], model=route.get("model"),
                            **connector_fields(route.get("provider")))
                turn["data"].update(reply=message["content"], routing=route, notices=message.get("notices"))
                yield turn
                if message.get("remembered") and turn["id"][5:] not in logged_recall:
                    yield entry("recall", "Memory recalled", source, id=f"recall:{key}", at=turn["at"],
                                data={"results": message["remembered"]})
                pending = None
        if pending:
            yield pending


def entries(storage, threads, can_undo, *, pinecone=None, mail_connected=False):
    from .pages import can_undo as can_undo_page
    with storage.lock():
        state = storage.load()
        activity = state.get("activity", [])
        artifacts = state.get("artifacts", {})
        undo_artifacts = state.get("artifact_undo", {})
        activity = [{**event, "undoable": artifacts.get(undo["id"], {}).get("revision") == undo["revision"]}
                    if (undo := undo_artifacts.get(event["id"])) else event for event in activity]
        recall_messages = {event.get("message_id") for event in activity if event["kind"] == "recall"}
        thread_list = threads.list()
        titles = {thread["id"]: thread["title"] for thread in thread_list}
        rows = [*activity, *chat_entries(threads, thread_list, recall_messages)]
        jobs = {job["id"]: job for job in state["jobs"]}
        rows.extend(action_entry(action, lambda item: can_undo_page(state, item) if item["kind"] == "page" else can_undo(item))
                    for action in state["actions"].values())
        scheduled = {row["data"]["job"]["id"]: row for row in rows if row["data"].get("job")}
        for job in jobs.values():
            original = scheduled.get(job["id"])
            if original:
                original["undoable"] = can_cancel(state, job)
                original["data"]["job"] = job
                original["data"]["next_due"] = job.get("next_fire_at", job["next_at"])
            elif job["status"] == "scheduled":
                rows.append(entry("reminder", f"Reminder scheduled · {job['message']}", job,
                                  id=f"job:{job['id']}", at=job.get("created_at"), data={"job": job}))
        for row in rows:
            if row["kind"] == "inbox" and row["title"].startswith("Email accepted · "):
                card = state.get("inbox", {}).get(row["data"].get("inbox_id"))
                if card:
                    row.update(action_id=card["id"], undoable=card["status"] == "accepted",
                               undone=card["status"] == "undone", undone_at=card.get("undone_at"))
        for index, route in enumerate(state.get("routing", [])):
            first = next(iter(route["order"]), {})
            rows.append(entry("routing", f"Routed to {first.get('name', 'a model')} · {route['label']}",
                              route, id=f"routing:{route.get('id') or str(route['at']) + ':' + str(index)}",
                              at=route["at"], model=first.get("model"), provider=first.get("provider"), data=route))
        for item in email_records(state):
            labels = {"app": "In app", "email": "Email"}
            delivery = {channel: {key: info[key] for key in ("status", "reason", "at", "next_at") if key in info}
                        for channel, info in item.get("delivery", {"app": {"status": "sent"}}).items()}
            status = " · ".join(f"{labels.get(channel, channel)} {info['status']}" for channel, info in delivery.items())
            late = f" · Late by {item['late_minutes']}m" if item.get("late_minutes") else ""
            data = {**item, "delivery": delivery, "delivery_summary": status}
            title = "Reminder delivered" if delivery.get("app", {}).get("status") == "sent" else "Reminder"
            rows.append(entry("reminder", f"{title} · {item['message']} · {status}{late}", item,
                              id=f"reminder:{item['id']}", at=item["delivered_at"], data=data,
                              error=any(info["status"] == "failed" for info in delivery.values())))
        if pinecone is not None:
            actionable(rows, state, pinecone, mail_connected)
    return [{**row, "thread_title": titles.get(row["thread_id"], row["thread_title"])} for row in rows]


class ActivityStream:
    """Share one change watcher across open timelines, including scheduler writes."""

    def __init__(self, *paths):
        self.paths = paths
        self.changed = threading.Condition()
        self.revision = 0
        self.subscribers = 0
        self.watching = False

    def signature(self):
        result = []
        for path in self.paths:
            try:
                stat = path.stat()
                result.append((stat.st_ino, stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                result.append(None)
        return result

    def watch(self, previous):
        with self.changed:
            while self.subscribers:
                self.changed.wait(0.65)
                current = self.signature()
                if current != previous:
                    previous = current
                    self.revision += 1
                    self.changed.notify_all()
            self.watching = False

    def subscribe(self):
        return closing(self.events())

    def events(self):
        with self.changed:
            self.subscribers += 1
            revision = self.revision
            if not self.watching:
                self.watching = True
                threading.Thread(target=self.watch, args=(self.signature(),), daemon=True).start()
        try:
            yield ("activity", {})
            while True:
                with self.changed:
                    updated = self.changed.wait_for(lambda: self.revision != revision, timeout=12)
                    revision = self.revision
                yield ("activity", {}) if updated else None
        finally:
            with self.changed:
                self.subscribers -= 1
                if not self.subscribers:
                    self.changed.notify_all()
