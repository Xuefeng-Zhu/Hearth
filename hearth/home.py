"""Build the Home snapshot and cache the Open-Meteo forecast."""
import json
import math
import threading
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from . import panels
from .gateway_tools import scrub
from .reminder_config import quiet_until, saved
from .storage import HearthError, iso, new_id

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_LOCATION = "Redmond, WA"
DEFAULT_PLACE = {"name": DEFAULT_LOCATION, "latitude": 47.674, "longitude": -122.1215}
WEATHER_MINUTES = 30
WEATHER_RETRY_MINUTES = 5
TITLES = {
    "today": "Today", "inbox": "Inbox to review", "weather": "Weather & clock", "files": "Recent files",
    "memory": "Memory", "activity": "Activity", "connections": "Connections health",
}


def weather_state(state):
    return {"location": DEFAULT_LOCATION, "place": DEFAULT_PLACE, "value": None,
            "updated_at": None, "attempted_at": None, "error": None, "revision": "", **state.get("weather", {})}


def open_meteo(host, path, parameters):
    with urlopen(f"https://{host}.open-meteo.com/v1/{path}?{urlencode(parameters)}", timeout=7) as response:
        return json.loads(response.read(96 * 1024))


def weather_value(row):
    place = row["place"]
    if not place:
        matches = open_meteo("geocoding-api", "search", {"name": row["location"], "count": 1, "language": "en"})
        if not matches.get("results"):
            raise HearthError("Open-Meteo couldn’t find this location. Try a city and state or country.")
        result = matches["results"][0]
        place = {"name": ", ".join(dict.fromkeys(result[key] for key in ("name", "admin1", "country")
                                                   if result.get(key))),
                 "latitude": result["latitude"], "longitude": result["longitude"]}
    forecast = open_meteo("api", "forecast", {
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": str(PACIFIC),
        "current": "temperature_2m,weather_code", "temperature_unit": "fahrenheit", "forecast_days": 1,
    })["current"]
    temperature, code = forecast["temperature_2m"], forecast["weather_code"]
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or type(code) is not int:
        raise HearthError("Open-Meteo returned incomplete current conditions.")
    return place, {"temperature": round(temperature), "code": code}


class Home:
    def __init__(self, app):
        self.app = app
        self.storage = app.storage
        self.panels = panels.Refreshes(app)
        self.weather_lock = threading.Lock()
        self.worker_lock = threading.Lock()

    def settings(self):
        row = weather_state(self.storage.load())
        return {key: row[key] for key in ("location", "error")}

    def save_settings(self, body):
        if body.keys() != {"location"}:
            raise HearthError("Enter a weather location.")
        location = panels.text(body["location"], 120)
        if len(location) < 2:
            raise HearthError("Enter a city, region or postal code.")
        with self.storage.lock():
            state = self.storage.load()
            if weather_state(state)["location"] != location:
                state["weather"] = {"location": location, "revision": new_id(),
                                    "place": DEFAULT_PLACE if location.casefold() == DEFAULT_LOCATION.casefold() else None}
                self.storage.save(state)
        self.kick()
        return self.settings()

    def refresh_weather(self, clock=None, *, due=False):
        now = clock or datetime.now(timezone.utc)
        if not self.weather_lock.acquire(blocking=False):
            return False
        try:
            row = weather_state(self.storage.load())
            attempted = row["attempted_at"]
            interval = WEATHER_RETRY_MINUTES if row["error"] else WEATHER_MINUTES
            if due and attempted and datetime.fromisoformat(attempted) + timedelta(minutes=interval) > now:
                return False
            if self.app.restoring():
                return False
            try:
                place, value = weather_value(row)
                changes = {"place": place, "value": value, "updated_at": iso(clock), "error": None}
            except HearthError as error:
                changes = {"error": str(error)}
            except (OSError, HTTPException, ValueError, KeyError, TypeError):
                changes = {"error": "Open-Meteo weather is unavailable. Try refreshing."}
            with self.storage.lock():
                state = self.storage.load()
                if self.app.restoring() or weather_state(state)["revision"] != row["revision"]:
                    return False
                state["weather"] = {**row, **changes, "attempted_at": iso(clock)}
                self.storage.save(state)
                return True
        finally:
            self.weather_lock.release()

    def run_due(self, clock=None):
        if self.app.restoring() or not self.worker_lock.acquire(blocking=False):
            return 0
        try:
            count = self.panels.run_due(clock)
            return count + self.refresh_weather(clock, due=True)
        finally:
            self.worker_lock.release()

    def kick(self):
        # A held worker lock means the next scheduler pass can pick up any newly due items.
        if not self.worker_lock.locked():
            threading.Thread(target=self.run_due, daemon=True, name="hearth-home-refresh").start()

    def snapshot(self, clock=None):
        now = clock or datetime.now(timezone.utc)
        state = self.storage.load()
        config = saved(state)
        quiet = quiet_until(now, config)
        jobs = sorted((item for item in state["jobs"] if item["status"] == "scheduled"),
                      key=lambda item: item.get("next_fire_at") or item["next_at"])
        inbox = sorted((card for card in state.get("inbox", {}).values() if card["status"] == "review"),
                       key=lambda card: card["received_at"], reverse=True)
        files = sorted((item for item in state.get("artifacts", {}).values() if not item.get("deleted")),
                       key=lambda item: item.get("updated_at") or item["created_at"], reverse=True)
        pinecone = self.app.memory_index.pinecone_status(self.app.agent.config)
        rows = sorted((entry for entry in self.app.timeline_info()["entries"] if entry.get("at")),
                      key=lambda entry: datetime.fromisoformat(entry["at"]), reverse=True)
        zone = ZoneInfo(config["timezone"])
        today = now.astimezone(zone).date()
        rows_today = [row for row in rows if datetime.fromisoformat(row["at"]).astimezone(zone).date() == today]
        report = self.app.connection_info(pinecone)
        connections = []
        for identity, entry in report["providers"].items():
            if entry["status"] not in ("connected", "unauthorized"):
                continue
            index_state = entry.get("index_state")
            ok = (entry["status"] == "connected" and entry.get("test_status") not in ("failed", "denied")
                  and index_state != "Unavailable")
            item = {"id": identity, "name": entry["name"], "ok": ok}
            if index_state and ok:
                item["state"] = index_state
            connections.append(item)
        weather = weather_state(state)
        built = {
            "today": {"quiet_until": iso(quiet) if quiet else None,
                      "quiet_enabled": config["quiet_start"] != config["quiet_end"],
                      "quiet_start": config["quiet_start"], "quiet_end": config["quiet_end"],
                      "jobs": [{"message": job["message"], "at": job.get("next_fire_at") or job["next_at"]}
                               for job in jobs[:3]]},
            "inbox": {"count": len(inbox), "items": [{"title": card.get("subject") or card.get("proposal", {}).get("title")
                                                     or "Untitled message", "at": card["received_at"]}
                                                    for card in inbox[:3]]},
            "files": {"items": [{key: item[key] for key in ("id", "title", "format")} for item in files[:4]]},
            "memory": {"count": len(self.storage.files()), "last_sync": pinecone["last_sync"],
                       "pinecone": pinecone["state"], "record_count": pinecone["record_count"]},
            "activity": {"count": len(rows_today), "errors": sum(bool(row.get("error")) for row in rows_today),
                         "items": [{key: row[key] for key in ("at", "title", "kind")} for row in rows[:5]]},
            "connections": {"items": connections, "error": report.get("scan_error")},
            "weather": {key: weather[key] for key in ("location", "value", "updated_at", "attempted_at", "error")}
                       | {"name": (weather["place"] or {}).get("name", weather["location"])},
        }
        return scrub({"layout": panels.layout(state), "builtin": built, "panels": state.get("panels", {}),
                      "timezone": config["timezone"], "clock_zone": str(PACIFIC), **self.app.brain_status()})

    def adjust(self, body):
        with self.storage.lock():
            state = self.storage.load()
            result = panels.adjust_layout(state, body)
            self.storage.save(state)
            return result

    def toggle(self, body):
        with self.storage.lock():
            state = self.storage.load()
            row = panels.panel(state, body.get("id"))
            if row["kind"] != "checklist" or row["source"]["type"] != "static":
                raise HearthError("Only a static checklist can be checked off here.")
            index, checked = body.get("index"), body.get("checked")
            items = row["source"]["value"]
            if body.get("revision") != row["revision"]:
                raise HearthError("This checklist changed. Refresh Home and try again.")
            if type(index) is not int or not 0 <= index < len(items) or type(checked) is not bool:
                raise HearthError("Choose a checklist item and its checked state.")
            items[index]["checked"] = checked
            row.update(panels.initial_values(row, datetime.now(timezone.utc)), revision=new_id())
            self.storage.save(state)
            return row

    def panel_chat(self, identity):
        if isinstance(identity, str) and identity in TITLES:
            title, value = TITLES[identity], self.snapshot()["builtin"][identity]
        else:
            row = panels.panel(self.storage.load(), identity)
            title = row["title"]
            value = {key: row[key] for key in ("kind", "value", "updated_at", "error")}
        with self.storage.lock():
            return self.app.threads.create(title=f"About {title}"[:80],
                                           panel_context={"title": title, "snapshot": value})
