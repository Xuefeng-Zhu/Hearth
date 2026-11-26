"""Exact method/path pairs and request policies for Hearth."""

import re

from . import (
    approvals, box, browserbase, feed, page_policy, proactivity, recall, reminder_config, search, uploads, voice,
    voice_call,
)
from .http_requests import JSON_LIMIT, MULTIPART_HEADER_LIMIT, JSONShape, Route, list_of

LARGE_JSON = 160_000
EVENT_JSON = 48_000
ARTIFACT_JSON = 8 * box.MAX_BYTES
WAIT = -1
TRY = 0
SHORT_WAIT = 5
AUTOMATION_READ = "Hearth could not read automation data."
AUTOMATION_WRITE = "Hearth could not update automation data."


def json_route(handler, operation="", *, required=None, optional=None, limit=JSON_LIMIT, **policy):
    return Route(handler, operation, shape=JSONShape(required or {}, optional or {}), media="json", limit=limit,
                 origin=True, **policy)


def field_types(defaults):
    return {key: list_of(str) if isinstance(value, list) else type(value) for key, value in defaults.items()}


GET = {
    "/health": Route("get_health", during_restore=True),
    "/api/state": Route("get_state", during_restore=True),
    "/api/transcript": Route("get_transcript"),
    "/api/threads": Route("get_threads"),
    "/api/threads/summary": Route("get_threads_summary"),
    "/api/home": Route("get_home", during_restore=True),
    "/api/goals/links": Route("get_goals_links"),
    "/api/feed": Route("get_feed"),
    "/api/feed/settings": Route("get_feed_settings"),
    "/api/proactivity/settings": Route("get_proactivity_settings"),
    "/api/proactivity/pass": Route("get_proactivity_pass", tick_token=True),
    "/api/home/settings": Route("get_home_settings"),
    "/api/connections": Route("get_connections"),
    "/api/voice/call/status": Route("get_voice_call_status"),
    "/api/brain": Route("get_brain"),
    "/api/brain/models": Route("get_brain_models"),
    "/api/checkpoints": Route("get_checkpoints"),
    "/api/timeline": Route("get_timeline"),
    "/api/timeline/events": Route("get_timeline_events", origin=True),
    "/api/skills": Route("get_skills"),
    "/api/skills/detail": Route("get_skills_detail"),
    "/api/memory/settings": Route("get_memory_settings"),
    "/api/memory/review": Route("get_memory_review"),
    "/api/search/settings": Route("get_search_settings"),
    "/api/approvals": Route("get_approvals", storage_error=AUTOMATION_READ),
    "/api/approvals/settings": Route("get_approvals_settings", storage_error=AUTOMATION_READ),
    "/api/event-automations": Route("get_event_automations", storage_error=AUTOMATION_READ),
    "/api/tasks": Route("get_tasks", storage_error=AUTOMATION_READ),
    "/api/reminders/settings": Route("get_reminders_settings"),
    "/api/reminders": Route("get_reminders"),
    "/api/inbox": Route("get_inbox"),
    "/api/reminders/outbox": Route("get_reminders_outbox"),
    "/api/pages": Route("get_pages"),
    "/api/pages/detail": Route("get_pages_detail"),
    "/api/artifacts": Route("get_artifacts"),
    "/api/artifacts/settings": Route("get_artifacts_settings"),
    "/api/artifacts/detail": Route("get_artifacts_detail"),
    "/api/artifacts/file": Route("get_artifacts_file"),
    "/api/memory/reindex": Route("get_memory_reindex"),
    "/api/memory/chat": Route("get_memory_chat"),
    "/api/memory": Route("get_memory"),
    "/api/uploads/detail": Route("get_upload", "detail"),
    "/api/uploads/file": Route("get_upload", "file"),
}

GET_STATIC = {"GET": Route("get_static", during_restore=True)}
GET_PAGE = {"GET": Route("get_page")}
PATH_PARAMS = (
    (re.compile(r"/api/browse/screenshots/(?P<name>demo\.png|" + browserbase.SCREENSHOT_ID.pattern + ")"),
     {"GET": Route("get_screenshot")}),
    (re.compile(r"/pages/(?P<id>[a-f0-9]{32})"), GET_PAGE),
    (re.compile(r"/pages/(?P<id>[a-f0-9]{32})/v/(?P<version>[1-9][0-9]{0,8})"), GET_PAGE),
    (re.compile(r"/p/(?P<token>" + page_policy.TOKEN.pattern + ")"), GET_PAGE),
)


def variant(value, shapes):
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        return False
    shape = shapes.get(value["type"])
    return shape is not None and shape({key: item for key, item in value.items() if key != "type"})


SCHEDULES = {
    "once": JSONShape({"at": str}),
    "interval": JSONShape({"minutes": int}),
    "cron": JSONShape({"cron": str}),
    # A saved daily or weekly schedule may include its derived cron expression.
    "daily": JSONShape({"time": str}, {"cron": str}),
    "weekly": JSONShape({"time": str, "days": list_of(int)}, {"cron": str}),
}


def schedule(value):
    return variant(value, SCHEDULES)


TRIGGERS = {
    "email": JSONShape(optional={"sender": str, "subject": (str, type(None)), "attachment": bool}),
    "reminder": JSONShape(optional={"job_id": (str, type(None))}),
    "feed": JSONShape(optional={"kind": str, "topic": (str, type(None))}),
    "schedule": JSONShape({"schedule": schedule}, {"timezone": (str, type(None))}),
}

ACTIONS = {
    "prompt": JSONShape({"prompt": str}, {"thread_id": str}),
    "reminder": JSONShape({"message": str, "delay_minutes": int}),
    "save_attachments": JSONShape({"destination": str}),
    "feed_card": JSONShape({"title": str, "topic": str}),
    "email_summary": JSONShape(),
}

TASK_REQUIRED = {"name": str, "instruction": str, "schedule": schedule}
TASK_OPTIONAL = {"timezone": (str, type(None)), "delivery": (str, type(None)), "enabled": (bool, type(None))}
EVENT_REQUIRED = {"name": str, "trigger": lambda value: variant(value, TRIGGERS),
                  "actions": list_of(lambda value: variant(value, ACTIONS))}
GOAL_FIELDS = {"title": str, "target_date": (str, type(None)),
               "links": list_of(JSONShape({"kind": str, "id": str})),
               "checkin": lambda value: value is None or JSONShape({"cadence": str, "time": str}, {"day": int})(value)}
MEMORY_FIELDS = field_types(recall.DEFAULTS) | {"min_similarity": (int, float)}
SEARCH_FIELDS = field_types(search.DEFAULTS)
FILTERS = {"kind": (str, type(None)), "thread_id": (str, type(None))}
BRAIN = {"provider": str, "model": str}
ID = {"id": str}
THREAD = {"thread_id": str}
REVISION = {"revision": str}
PAGE_FIELDS = {"version": int, "current": int}


def automation_route(handler, operation, *, required=None, optional=None, limit=JSON_LIMIT):
    return json_route(handler, operation, required=required, optional=optional, limit=limit,
                      lock_timeout=WAIT, storage_error=AUTOMATION_WRITE)


def artifact_route(operation, *, required=None, optional=None, limit=ARTIFACT_JSON, lock_timeout=None):
    return json_route("post_artifact", operation, required=required, optional=optional, limit=limit,
                      lock_timeout=lock_timeout)


POST = {
    "/api/scheduler/tick": Route("post_scheduler_tick", origin=True, tick_token=True,
                                 storage_error="Hearth could not run the scheduler tick."),
    "/api/workers/stop": json_route("post_stop", "workers", required={"turn_id": str}, optional=ID,
                                   storage_error="Hearth could not stop the worker."),
    "/api/chat/stop": json_route("post_stop", "chat", required=THREAD | {"reply_id": str}),
    "/api/chat": json_route("post_chat", optional=THREAD | {"message": str, "attachment_ids": list_of(str)},
                            lock_timeout=WAIT),
    "/api/browse/approve": json_route("post_browse_approve", required=ID | THREAD, lock_timeout=WAIT),
    "/api/browse/settings": json_route("post_browse_settings", optional={"allowed": bool}, lock_timeout=TRY),
    "/api/approve": json_route("post_action", "approve", required=ID, lock_timeout=TRY),
    "/api/undo": json_route("post_action", "undo", required=ID, lock_timeout=TRY),
    "/api/redo": json_route("post_action", "redo", required=ID, lock_timeout=TRY),
    "/api/threads/create": json_route("post_thread", "create", lock_timeout=WAIT),
    "/api/threads/rename": json_route("post_thread", "rename", required=THREAD | {"title": str}, lock_timeout=WAIT),
    "/api/threads/delete": json_route("post_thread", "delete", required=THREAD, lock_timeout=WAIT),
    "/api/threads/share": json_route("post_thread", "share", required=THREAD | {"message_id": str}, lock_timeout=WAIT),
    "/api/threads/summary/reset": json_route("post_thread", "reset", required=THREAD, lock_timeout=WAIT),
    "/api/skills/create": json_route("post_skills", "create", required={"markdown": str}, limit=LARGE_JSON, lock_timeout=TRY),
    "/api/skills/save": json_route("post_skills", "save", required=ID | REVISION | {"markdown": str}, limit=LARGE_JSON,
                                  lock_timeout=TRY),
    "/api/skills/delete": json_route("post_skills", "delete", required=ID | REVISION, limit=LARGE_JSON, lock_timeout=TRY),
    "/api/skills/duplicate": json_route("post_skills", "duplicate", required=ID, limit=LARGE_JSON, lock_timeout=TRY),
    "/api/skills/try": json_route("post_skills", "try", required=ID, limit=LARGE_JSON, lock_timeout=TRY),
    "/api/connections/rescan": json_route("post_connections", "rescan", lock_timeout=SHORT_WAIT),
    "/api/connections/test": json_route("post_connections", "test", required={"provider": str}, lock_timeout=SHORT_WAIT),
    "/api/connections/settings": json_route("post_connections", "settings", required={"provider": str, "value": str},
                                           lock_timeout=TRY),
    "/api/brain/test": json_route("post_brain", "test", required=BRAIN, optional={"pool": list}, lock_timeout=TRY),
    "/api/brain/settings": json_route("post_brain", "settings", required=BRAIN,
                                     optional={"pool": list, "parallel_workers": int}, lock_timeout=TRY),
    "/api/brain/route": json_route("post_brain", "route", required=BRAIN, optional={"pool": list, "prompt": str}),
    "/api/memory/search": json_route("post_memory", "search", required={"query": str}, optional=FILTERS,
                                     limit=LARGE_JSON, lock_timeout=SHORT_WAIT),
    "/api/memory/sync": json_route("post_memory", "sync", limit=LARGE_JSON, lock_timeout=TRY),
    "/api/memory/reindex": json_route("post_memory", "reindex", limit=LARGE_JSON, lock_timeout=TRY),
    "/api/memory/forget": json_route("post_memory", "forget", required={"path": str}, limit=LARGE_JSON,
                                     optional={"item_id": str, "message_id": str, "revision": str}, lock_timeout=TRY),
    "/api/memory/profile": json_route("post_memory", "profile", limit=LARGE_JSON, lock_timeout=TRY,
                                      required={"profile": dict, "notes": str, "revision": (str, type(None))}),
    "/api/memory/write": json_route("post_memory", "write", required=REVISION | {"path": str, "content": str},
                                    limit=LARGE_JSON, lock_timeout=TRY),
    "/api/memory/move": json_route("post_memory", "move", required=REVISION | {"path": str, "target": str},
                                   limit=LARGE_JSON, lock_timeout=TRY),
    "/api/memory/settings": json_route("post_preference_settings", "memory", optional=MEMORY_FIELDS,
                                       limit=LARGE_JSON, lock_timeout=TRY),
    "/api/memory/test": json_route("post_preference_test", "memory", limit=LARGE_JSON, lock_timeout=TRY,
                                   required={"selection": JSONShape(optional=MEMORY_FIELDS), "query": str}, optional=FILTERS),
    "/api/search/settings": json_route("post_preference_settings", "search", optional=SEARCH_FIELDS, lock_timeout=TRY),
    "/api/search/test": json_route("post_preference_test", "search", lock_timeout=TRY,
                                   required={"selection": JSONShape(optional=SEARCH_FIELDS), "query": str}),
    "/api/pages/revert": json_route("post_pages", "revert", required=ID | PAGE_FIELDS, lock_timeout=WAIT),
    "/api/pages/share": json_route("post_pages", "share", required=ID | {"version": int}, optional={"current": int},
                                   lock_timeout=WAIT),
    "/api/pages/box": json_route("post_pages", "box", required=ID | {"version": int}, optional={"current": int},
                                 lock_timeout=WAIT),
    "/api/pages/revoke": json_route("post_pages", "revoke", required=ID, optional=PAGE_FIELDS, lock_timeout=WAIT),
    "/api/memory/review/settings": json_route("post_memory_review", "settings", required={"enabled": bool, "time": str},
                                             lock_timeout=WAIT),
    "/api/memory/review/decision": json_route("post_memory_review", "decision", required={"digest": str, "operation": str},
                                             optional={"item": str}, lock_timeout=WAIT),
    "/api/memory/review/run": json_route("post_memory_review", "run", lock_timeout=WAIT),
    "/api/feed/settings": json_route("post_feed", "settings", optional=field_types(feed.DEFAULTS), lock_timeout=WAIT),
    "/api/feed/feedback": json_route("post_feed", "feedback", required=ID | {"operation": str}, lock_timeout=WAIT),
    "/api/feed/chat": json_route("post_feed", "chat", required=ID, lock_timeout=WAIT),
    "/api/feed/idea": json_route("post_feed", "idea", required=ID | {"operation": str}, lock_timeout=WAIT),
    "/api/feed/refresh": json_route("post_feed", "refresh"),
    "/api/proactivity/pass": json_route("post_proactivity", "pass", tick_token=True),
    "/api/proactivity/settings": json_route("post_proactivity", "settings", optional=field_types(proactivity.DEFAULTS),
                                            lock_timeout=WAIT),
    "/api/proactivity/do": json_route("post_proactivity", "do", required=ID, lock_timeout=WAIT),
    "/api/proactivity/dismiss": json_route("post_proactivity", "dismiss", required=ID, lock_timeout=WAIT),
    "/api/proactivity/snooze": json_route("post_proactivity", "snooze", required=ID | {"days": int}, lock_timeout=WAIT),
    "/api/proactivity/block": json_route("post_proactivity", "block", required=ID, lock_timeout=WAIT),
    "/api/goals/create": json_route("post_goal", "create", required={"title": str}, optional=GOAL_FIELDS, lock_timeout=WAIT),
    "/api/goals/update": json_route("post_goal", "update", required=ID, optional=REVISION | GOAL_FIELDS, lock_timeout=WAIT),
    "/api/goals/checkin": json_route("post_goal", "checkin", required=ID, lock_timeout=WAIT,
                                     optional=REVISION | {"note": str, "progress": (int, type(None))}),
    "/api/goals/delete": json_route("post_goal", "delete", required=ID, optional=REVISION, lock_timeout=WAIT),
    "/api/home/layout": json_route("post_home", "layout", required=ID | {"operation": str}, lock_timeout=WAIT,
                                   optional={"target": str, "position": str}),
    "/api/home/checklist": json_route("post_home", "checklist", required=ID | REVISION | {"index": int, "checked": bool},
                                      lock_timeout=WAIT),
    "/api/home/settings": json_route("post_home", "settings", required={"location": str}, lock_timeout=WAIT),
    "/api/home/chat": json_route("post_home", "chat", required=ID, lock_timeout=WAIT),
    "/api/home/refresh": json_route("post_home", "refresh", required=ID),
    "/api/uploads": Route("post_upload", origin=True, media="multipart",
                          limit=uploads.MAX_BYTES + 2 * MULTIPART_HEADER_LIMIT,
                          storage_error="Hearth could not save the attachment."),
    "/api/uploads/box": json_route("post_upload_box", required=ID | THREAD, lock_timeout=WAIT,
                                   storage_error="Hearth could not save the attachment."),
    "/api/approvals/settings": automation_route("post_approvals", "settings", optional=dict.fromkeys(approvals.DEFAULTS, str)),
    "/api/approvals/approve": automation_route("post_approvals", "approve", required=ID),
    "/api/approvals/edit": automation_route("post_approvals", "edit", required=ID | {"changes": dict}),
    "/api/approvals/decline": automation_route("post_approvals", "decline", required=ID),
    "/api/tasks/create": automation_route("post_tasks", "create", required=TASK_REQUIRED, optional=TASK_OPTIONAL),
    "/api/tasks/preview": automation_route("post_tasks", "preview",
                                           optional=TASK_REQUIRED | TASK_OPTIONAL | {"id": (str, type(None))}),
    "/api/tasks/update": automation_route("post_tasks", "update", required=ID, optional=TASK_REQUIRED | TASK_OPTIONAL),
    "/api/tasks/pause": automation_route("post_tasks", "pause", required=ID),
    "/api/tasks/run": automation_route("post_tasks", "run", required=ID),
    "/api/tasks/delete": automation_route("post_tasks", "delete", required=ID),
    "/api/event-automations/create": automation_route("post_event_automations", "create", limit=EVENT_JSON,
                                                      required=EVENT_REQUIRED, optional={"enabled": bool}),
    "/api/event-automations/update": automation_route("post_event_automations", "update", required=ID, limit=EVENT_JSON,
                                                      optional=EVENT_REQUIRED | {"enabled": bool}),
    "/api/event-automations/delete": automation_route("post_event_automations", "delete", required=ID, limit=EVENT_JSON),
    "/api/inbox/poll": json_route("post_inbox", "poll", optional={"force": bool}),
    "/api/inbox/accept": json_route("post_inbox", "accept", required=ID),
    "/api/inbox/dismiss": json_route("post_inbox", "dismiss", required=ID),
    "/api/inbox/undo": json_route("post_inbox", "undo", required=ID),
    "/api/inbox/edit": json_route("post_inbox", "edit", required=ID | {"title": str, "kind": str},
                                  optional={"summary": str, "at": (str, type(None))}),
    "/api/reminders/settings": json_route("post_reminders", "settings", optional=field_types(reminder_config.DEFAULTS)),
    "/api/reminders/test": json_route("post_reminders", "test", optional={"channel": (str, type(None))}),
    "/api/reminders/inspect": json_route("post_reminders", "inspect", required={"token": str}),
    "/api/reminders/action": json_route("post_reminders", "action", required={"token": str}),
    "/api/reminders/cancel": json_route("post_reminders", "cancel", required=ID),
    "/api/reminders/create": json_route("post_reminders", "create", required={"message": str},
                                        optional={"at": (str, type(None)), "cron": (str, type(None)), "note": str,
                                                  "channel": (str, type(None)), "urgent": bool}),
    "/api/artifacts/settings": artifact_route("settings", optional=field_types(box.DEFAULTS), lock_timeout=WAIT),
    "/api/artifacts/retry": artifact_route("retry", required=ID),
    "/api/artifacts/undo": artifact_route("undo", required=ID),
    "/api/artifacts/delete": artifact_route("delete", required=ID | REVISION),
    "/api/artifacts/ask": artifact_route("ask", required={"question": str}, optional={"artifact_ids": list_of(str)},
                                        limit=JSON_LIMIT),
    "/api/voice/call/token": json_route("post_call_token"),
    "/api/voice/call/query": json_route("post_call_query", required=THREAD | {"query": str}),
    "/api/voice/call/report": json_route("post_call_report", lock_timeout=WAIT, limit=voice_call.MAX_REPORT_BYTES,
                                         required=ID | THREAD | {"duration": int, "demo": bool,
                                                                "lines": list_of(JSONShape({"role": str, "text": str}))}),
    "/api/voice/redact": json_route("post_voice", "redact", required={"text": str}),
    "/api/voice/transcribe": Route("post_voice", "transcribe", origin=True, media="audio", limit=voice.MAX_AUDIO),
}

EXACT = {}
for method, routes in (("GET", GET), ("POST", POST)):
    for path, route in routes.items():
        EXACT.setdefault(path, {})[method] = route


def route_for(path, static):
    if path in static:
        return GET_STATIC, {}
    if path in EXACT:
        return EXACT[path], {}
    for pattern, methods in PATH_PARAMS:
        if match := pattern.fullmatch(path):
            return methods, match.groupdict()
    return {}, {}
