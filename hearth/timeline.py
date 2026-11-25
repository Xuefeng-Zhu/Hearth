import threading
from contextlib import closing

from .connections import catalog_entry
from .gateway_tools import scrub
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
    elif kind == "gateway":
        request = action["request"]
        provider = request["provider"]
        title = f"{'Proposed' if status == 'pending' else 'Requested'} {request['method']} {request['path']}"
    elif kind == "reminder":
        title += f" · {action['job']['message']}"
    elif action.get("paths"):
        title += f" · {', '.join(action['paths'])}"
    elif kind == "remember" and status == "complete":
        title = f"Memory saved · {action['fact']}"
    return entry(kind, compact(title, 180), action, id=f"action:{action['id']}",
                 at=action.get("updated_at", action["at"]), provider=provider, model=action.get("model"),
                 error=error, action_id=action["id"], undoable=can_undo(action),
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


def entries(storage, threads, can_undo):
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
        rows.extend(action_entry(action, can_undo) for action in state["actions"].values())
        scheduled = {row["data"]["job"]["id"]: row for row in rows if row["data"].get("job")}
        for job in state["jobs"]:
            if job["status"] != "scheduled":
                continue
            original = scheduled.get(job["id"])
            if original:
                if job["next_at"] != original["data"]["job"]["next_at"]:
                    original["data"]["next_due"] = job["next_at"]
            else:
                rows.append(entry("reminder", f"Reminder scheduled · {job['message']}", job,
                                  id=f"job:{job['id']}", at=job.get("created_at"), data={"job": job}))
        for index, route in enumerate(state.get("routing", [])):
            first = next(iter(route["order"]), {})
            rows.append(entry("routing", f"Routed to {first.get('name', 'a model')} · {route['label']}",
                              route, id=f"routing:{route.get('id') or str(route['at']) + ':' + str(index)}",
                              at=route["at"], model=first.get("model"), provider=first.get("provider"), data=route))
        rows.extend(entry("reminder", f"Reminder delivered · {item['message']}", item,
                          id=f"reminder:{item['id']}", at=item["delivered_at"], data=item)
                    for item in state["reminders"])
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
