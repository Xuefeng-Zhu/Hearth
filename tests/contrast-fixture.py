"""Run the contrast test against a disposable workspace with representative data."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from hearth import scheduler, timeline
from hearth.agent import DEMO_FILES
from hearth.browserbase import TEST_PATH
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import Storage, iso
from hearth.threads import MAIN_ORIGIN
from test_reminder_delivery import MailGateway


class ContrastGateway(MailGateway):
    def discover(self):
        return {"agentmail": {"fixture-mail"}, "exa": {"fixture-search"}}, {"agentmail", "exa", "box"}

    def request(self, path, body, headers, timeout):
        assert path == f"browserbase/{TEST_PATH}"
        raise ConnectorError("No Browserbase connection.", 404, missing_connection=True)


def seed(app, gateway):
    now = datetime.now(timezone.utc)
    storage = app.storage
    app.threads.append("main", "user", "What should I pack for Seattle?")
    reply = app.threads.append(
        "main", "assistant",
        "### Seattle weekend\n\nPack a light rain jacket and comfortable shoes.\n\n"
        "- Start at **Pike Place Market**.\n- See the [Space Needle](https://www.spaceneedle.com/).\n\n"
        "| Stop | Time |\n| --- | --- |\n| Kerry Park | Sunset |\n\n```text\nSeattle, WA\n```",
        remembered=[{"id": "fixture-memory", "path": "USER.md", "line": 1, "backend": "pinecone", "score": 0.91}],
        notices=["The first connector timed out. Tried another brain."],
        routing={"name": "Hugging Face", "provider": "huggingface", "model": "deepseek-ai/DeepSeek-V4.1-Flash:fastest",
                 "class": "quick", "reason": "Favors speed and lower cost", "label": "Quick chat"},
    )
    with storage.lock():
        side = app.threads.create()
        app.threads.rename(side["id"], "Seattle notes")
        app.threads.append(side["id"], "user", "Any good viewpoints?")
        app.threads.append(side["id"], "assistant", "Try **Kerry Park** at sunset.")
        app.threads.append(side["id"], "user", "Can you expand on the trip?")
        app.threads.append(side["id"], "assistant", "\n\n".join(
            f"{number}. Visit the waterfront. Take the scenic route through the market and leave time for a café."
            for number in range(1, 50)
        ))
        state = storage.load()
        scheduler.add_job(state, "Check the weather", now, at=iso(now + timedelta(days=1)),
                          channel="both", note="Bring a jacket")
        storage.save(state)
    app.agent.checkpoint()
    app.agent.send_email(["traveler@example.invalid"], "Seattle itinerary", "Let’s meet at Pike Place Market.")
    app.agent.memory_write([{"path": "topics/seattle.md", "content": "# Seattle\nVisit Kerry Park."}])
    for kind in ("recall", "remember", "reminder", "gateway", "search", "routing", "brain", "voice",
                 "artifact", "undo", "inbox", "thread", "tool"):
        timeline.record(storage, kind, f"Example {kind} activity", MAIN_ORIGIN,
                        provider="exa" if kind in {"search", "gateway"} else "huggingface",
                        model="Kimi-K3.1-Pro", error=kind in {"brain", "tool"}, undone=kind == "undo",
                        data={"detail": "This entry has expanded details.", "status": "failed" if kind == "tool" else "complete"})
    files = {}
    for fmt, (_, data) in DEMO_FILES.items():
        item = app.artifacts.create(fmt, {key: value for key, value in data.items() if key != "kind"}, kind="plan")
        files[item["id"]] = item
    app.artifacts.bind(files, "main", reply["id"])
    for number, (subject, text) in enumerate([
        ("Flight confirmation", "SFO to SEA. Departs 2030-02-01T10:00:00Z."),
        ("Order receipt", "Merchant: Store\nOrder total: $35.99"),
        ("School permission slip", "Bring it tomorrow at 8 am."),
    ]):
        gateway.messages.append({"message_id": str(number), "timestamp": iso(now), "subject": subject, "text": text,
                                 "from": "sender@example.invalid", "labels": ["received"]})
    app.inbox.poll(force=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=39519)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="hearth-contrast-") as temporary:
        storage = Storage(temporary)
        config = read_config(Path("config/connectors.json"))
        config["brain"] = {"provider": "mock", "model": ""}
        gateway = ContrastGateway()
        app = Application(storage, LocalCheckpoints(storage), config, gateway=gateway)
        app.scan_connections()
        seed(app, gateway)
        with HTTPServer(("127.0.0.1", args.port), app) as server:
            server.serve_forever()
