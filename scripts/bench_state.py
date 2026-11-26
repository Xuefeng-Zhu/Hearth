#!/usr/bin/env python3
"""Measure loopback polling with a disposable, synthetic Hearth workspace."""

import argparse
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from queue import SimpleQueue
from statistics import median
from tempfile import TemporaryDirectory
from threading import Thread, local
from time import perf_counter
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hearth import scheduler
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.server import Application, Handler
from hearth.storage import ROOT, Storage, atomic_write, iso


class MeasuredStorage(Storage):
    timing = local()

    @contextmanager
    def lock(self):
        with super().lock():
            started = perf_counter()
            try:
                yield
            finally:
                self.timing.held = getattr(self.timing, "held", 0) + perf_counter() - started


class OfflineGateway:
    def request(self, *args, **kwargs):
        raise ConnectorError("No provider in the benchmark.", missing_connection=True)

    json = request


def seed(app):
    storage, threads = app.storage, app.threads
    # Keep the mix of today's and older activity consistent at any run time.
    zone = ZoneInfo("America/Los_Angeles")
    now = datetime.now(zone).replace(hour=1, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    with storage.lock():
        index = threads.load_index()
        for number in range(1, 200):
            index[f"{number:032x}"] = {"title": f"Side chat {number}", "created_at": iso(now)}
        threads.save_index(index)
        for number, thread in enumerate(index):
            count = 500 if thread == "main" else 16
            rows = [{
                "id": f"message-{number}-{i}", "role": "assistant" if i % 2 else "user",
                "content": f"Entry {i}. " + "A fictional garden planning note with enough text for a reply. " * 16,
                "at": iso(now - timedelta(minutes=(count - i) + number * 20)),
                **({"action_ids": [f"action-{i}"]} if thread == "main" and i % 2 else {}),
            } for i in range(count)]
            atomic_write(threads.path(thread), "".join(json.dumps(row) + "\n" for row in rows))
        state = storage.load()
        thread_ids = list(index)
        for i in range(1200):
            identity = f"action-{i}"
            thread = thread_ids[i % len(index)]
            state["actions"][identity] = {
                "id": identity, "kind": "memory", "status": "complete", "title": "Saved a planning note",
                "thread_id": thread, "at": iso(now - timedelta(minutes=i + 10)), "detail": "Fictional result. " * 30,
            }
        for i in range(400):
            scheduler.add_job(state, f"Garden reminder {i}", clock=now - timedelta(minutes=i + 10),
                              at=iso(now + timedelta(days=1, minutes=i)))
        storage.save(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    timings = SimpleQueue()

    class MeasuredHandler(Handler):
        def do_GET(self):
            MeasuredStorage.timing.held = 0
            started = perf_counter()
            try:
                super().do_GET()
            finally:
                timings.put(((perf_counter() - started) * 1000, MeasuredStorage.timing.held * 1000))

    class BenchServer(ThreadingHTTPServer):
        def __init__(self, app):
            self.app = app
            super().__init__(("127.0.0.1", 0), MeasuredHandler)

    def request(server, route, tag=None):
        conn = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            conn.request("GET", route, headers={"If-None-Match": tag} if tag else {})
            response = conn.getresponse()
            size = len(response.read())
            elapsed, held = timings.get(timeout=10)
            return response.status, size, elapsed, held, response.getheader("ETag")
        finally:
            conn.close()

    def report(label, samples):
        statuses, sizes, elapsed, held, _ = zip(*samples)
        print(f"{label:19} {','.join(map(str, sorted(set(statuses)))):>6} {int(median(sizes)):>10,}"
              f" {median(elapsed):>10.3f} {median(held):>10.3f}")
        return samples[-1][-1]

    with TemporaryDirectory() as directory:
        storage = MeasuredStorage(directory)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        app = Application(storage, LocalCheckpoints(storage), config, gateway=OfflineGateway())
        seed(app)
        with BenchServer(app) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                print("200 threads, 500 Main messages, 16 per side chat, 1,200 actions, 400 jobs")
                print(f"{'Request':19} {'Status':>6} {'Body bytes':>10} {'Server ms':>10} {'Locked ms':>10}")
                for label, route in (("State", "/api/state"), ("Home", "/api/home")):
                    tag = report(f"{label} first", [request(server, route)])
                    report(f"{label} regular", [request(server, route) for _ in range(args.samples)])
                    if tag:
                        report(f"{label} unchanged", [request(server, route, tag) for _ in range(args.samples)])
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    main()
