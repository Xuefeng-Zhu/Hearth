import base64
import hashlib
import json
import shutil
import tempfile
import unittest
from contextlib import nullcontext
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

from hearth import approvals, self_update
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.server import Application
from hearth.storage import HearthError, Storage
from hearth.threads import MAIN_ORIGIN

BASE = "1" * 40
NEW_BASE = "2" * 40
MERGE = "3" * 40
DOC = "docs/self-update.md"
REQUEST = f"Hearth, add a test line to {DOC}."
REPO = self_update.DEFAULT_REPO


class GitHubGateway:
    def __init__(self):
        self.writes, self.brain, self.replies = [], [], []
        self.refs = {"main": BASE}
        self.blobs, self.trees, self.commits = {}, {}, {}
        self.pending, self.failed, self.strict = False, False, True
        self.force_pushes, self.missing_required, self.conflicts = False, False, False
        self.pull, self.runs = None, []
        self.interrupt = None
        self.install(BASE, None, {DOC: "# Improve Hearth\n"})
        self.install(NEW_BASE, BASE, {DOC: "# Improve Hearth\n", "README.md": "Unrelated change\n"})

    @staticmethod
    def identity(value):
        return hashlib.sha1(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def blob(self, content):
        sha = self.identity(content)
        self.blobs[sha] = content
        return sha

    def install(self, sha, parent, contents):
        tree = {path: self.blob(content) for path, content in contents.items()}
        root = self.identity(tree)
        self.trees[root] = tree
        self.commits[sha] = {"sha": sha, "tree": {"sha": root}, "parents": [{"sha": parent}] if parent else []}

    def completion(self, model, messages, tools, emit, **options):
        self.brain.append((messages, tools))
        return {"content": json.dumps(self.replies.pop(0))}

    def pull_response(self):
        branch = self.pull["branch"]
        return {**self.pull, "head": {"ref": branch, "sha": self.refs[branch], "repo": {"full_name": REPO}},
                "base": {"ref": "main", "sha": self.refs["main"], "repo": {"full_name": REPO}},
                "mergeable": not self.conflicts, "mergeable_state": "dirty" if self.conflicts else "clean"}

    def json(self, config, path, body=None, headers=None, *, method="GET", **options):
        assert config["connection_id"] == "gateway-fixture"
        assert path == f"repos/{REPO}" or path.startswith(f"repos/{REPO}/")
        route = urlsplit(path.removeprefix(f"repos/{REPO}").lstrip("/"))
        name = route.path
        if method != "GET":
            self.writes.append((method, name, body))
        if not name:
            return {"default_branch": "main"}
        if name.startswith("git/ref/heads/"):
            branch = name.removeprefix("git/ref/heads/")
            if branch not in self.refs:
                raise ConnectorError("Not found", 404)
            return {"object": {"sha": self.refs[branch]}}
        if name == "git/refs":
            branch = body["ref"].removeprefix("refs/heads/")
            assert branch.startswith("hearth/improve-") and branch not in self.refs
            self.refs[branch] = body["sha"]
            return {}
        if name.startswith("git/refs/heads/"):
            branch = name.removeprefix("git/refs/heads/")
            assert branch.startswith("hearth/improve-") and not body["force"]
            assert self.commits[body["sha"]]["parents"] == [{"sha": self.refs[branch]}]
            self.refs[branch] = body["sha"]
            return {}
        if name == "git/blobs":
            return {"sha": self.blob(body["content"])}
        if name.startswith("git/blobs/"):
            content = self.blobs[name.split("/")[-1]]
            return {"encoding": "base64", "content": base64.b64encode(content.encode()).decode()}
        if name == "git/trees":
            tree = dict(self.trees[body["base_tree"]])
            for item in body["tree"]:
                if item["sha"] is None:
                    tree.pop(item["path"], None)
                else:
                    tree[item["path"]] = item["sha"]
            root = self.identity(tree)
            self.trees[root] = tree
            return {"sha": root}
        if name.startswith("git/trees/"):
            assert parse_qs(route.query) == {"recursive": ["1"]}
            tree = self.trees[name.split("/")[-1]]
            return {"tree": [{"path": path, "sha": sha, "type": "blob", "mode": "100644",
                              "size": len(self.blobs[sha])} for path, sha in tree.items()]}
        if name == "git/commits":
            sha = self.identity(body)
            self.commits[sha] = {"tree": {"sha": body["tree"]}, "parents": [{"sha": body["parents"][0]}]}
            return {"sha": sha}
        if name.startswith("git/commits/"):
            return self.commits[name.split("/")[-1]]
        if name == "pulls":
            if method == "GET":
                branch = parse_qs(route.query)["head"][0].split(":")[1]
                return [self.pull_response()] if self.pull and branch == self.pull["branch"] else []
            self.pull = {"number": 66, "state": "open", "branch": body["head"], "title": body["title"],
                         "body": body["body"], "merged": False}
            if self.interrupt == "create":
                self.interrupt = None
                raise ConnectorError("Lost response", 504)
            return self.pull_response()
        if name == "pulls/66":
            if method == "PATCH":
                self.pull.update(body)
            return self.pull_response()
        if name == "branches/main/protection":
            if not self.strict:
                raise ConnectorError("Forbidden", 403)
            return {"required_status_checks": {"strict": True, "checks": [{"context": "test"}]},
                    "enforce_admins": {"enabled": True}, "allow_force_pushes": {"enabled": self.force_pushes}}
        if name.endswith("/check-runs"):
            runs = [] if self.missing_required else [
                {"name": "test", "status": "in_progress" if self.pending else "completed",
                 "conclusion": "failure" if self.failed else "success", "app": {"id": 1}}]
            return {"check_runs": runs, "total_count": len(runs)}
        if name.endswith("/status"):
            return {"statuses": []}
        if name == "pulls/66/merge":
            assert method == "PUT" and body == {"sha": self.refs[self.pull["branch"]], "merge_method": "squash"}
            self.commits[MERGE] = {"tree": self.commits[body["sha"]]["tree"], "parents": [{"sha": self.refs["main"]}]}
            self.refs["main"] = MERGE
            self.pull.update(state="closed", merged=True, merge_commit_sha=MERGE)
            if self.interrupt == "merge":
                self.interrupt = None
                raise ConnectorError("Lost response", 504)
            return {"merged": True, "sha": MERGE}
        if name == "actions/workflows/deploy.yml/runs":
            assert parse_qs(route.query)["head_sha"] == [MERGE]
            return {"workflow_runs": self.runs}
        raise AssertionError((method, name))

    def open(self, config, path, *, method, **options):
        assert config["connection_id"] == "gateway-fixture"
        branch = path.removeprefix(f"repos/{REPO}/git/refs/heads/")
        assert method == "DELETE" and branch.startswith("hearth/improve-")
        self.writes.append((method, branch, None))
        del self.refs[branch]
        return nullcontext()


class SelfUpdateTest(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.storage = Storage(root.name)
        self.gateway = GitHubGateway()
        self.app = Application(self.storage, LocalCheckpoints(self.storage), read_config(), gateway=self.gateway)
        self.app.agent.config["gateway"] = {"github": {"provider": "github", "connection_id": "gateway-fixture"}}
        self.app.agent.gateway_connections = self.app.agent.config["gateway"]
        self.app.agent.models = [{"provider": "openai", "model": "fixture"}]
        self.app.agent.brain_mode = "manual"
        self.updates = self.app.self_updates

    def draft(self, content="# Improve Hearth\nA new line.\n", *, path=DOC):
        self.gateway.replies[:] = [[path], {
            "title": "Add a test line", "summary": "Add one line to the guide.",
            "files": [{"path": path, "content": content}]}]

    def propose(self):
        self.draft()
        events = []
        self.app.agent.chat(REQUEST, lambda *event: events.append(event))
        self.assertEqual(events[-1][0], "done")
        message = events[-1][1]["message"]
        row = next(row for row in self.app.info()["self_updates"] if row["id"] == message["self_update_id"])
        self.assertEqual(self.row(row)["base"], BASE)
        return row

    def row(self, proposal):
        return self.updates.rows()[proposal["id"]]

    def poll(self, proposal):
        row = self.row(proposal)
        self.updates.try_step(self.updates.client(REPO), row)
        return self.row(proposal)

    def act(self, operation, proposal, feedback=""):
        return self.updates.act(operation, proposal["id"], "main", proposal["head"], feedback)

    def assert_no_merge(self):
        self.assertFalse(any(method == "PUT" for method, _, _ in self.gateway.writes))

    def test_proposal_explicit_approval_checks_deploy_and_revert(self):
        approvals.settings(self.storage, dict.fromkeys(approvals.CONNECTOR_CATEGORIES, "allow"))
        proposal = self.propose()
        self.assertIn("Proposed by Hearth on request in chat", self.gateway.pull["body"])
        self.assertEqual(proposal["files"], [{"path": DOC, "added": 1, "removed": 0}])
        self.assertIn("+A new line.", proposal["diff"])
        self.assertIn("/pull/66", proposal["url"])
        self.assertEqual(self.poll(proposal)["checks"], "passed")
        self.assert_no_merge()
        with self.assertRaisesRegex(HearthError, "latest diff"):
            self.act("approve", {**proposal, "head": NEW_BASE})
        with self.assertRaisesRegex(HearthError, "Chat approval card"):
            self.app.agent.prepare_approval("gateway_request", {"provider": "github", "method": "PUT",
                                            "path": f"repos/{REPO}/pulls/66/merge"})
        self.gateway.pending = True
        self.act("approve", proposal)
        self.assertEqual(self.poll(proposal)["status"], "waiting")
        self.assert_no_merge()
        self.gateway.pending = False
        self.assertEqual(self.poll(proposal)["status"], "updating")
        self.gateway.runs = [
            {"head_sha": MERGE, "head_branch": "other", "event": "push", "id": 99,
             "status": "completed", "conclusion": "failure"},
            {"head_sha": MERGE, "head_branch": "main", "event": "push", "id": 23, "status": "in_progress"},
        ]
        self.assertTrue(self.poll(proposal)["run_url"].endswith("/23"))
        self.app.version = MERGE
        self.assertEqual(self.poll(proposal)["status"], "updated")
        revert = self.updates.propose("Revert the last Hearth update", MAIN_ORIGIN, mode="revert", commit=Mock())
        self.assertEqual(revert["status"], "review")
        self.assertIn("-A new line.", revert["diff"])
        self.assertEqual(len(self.gateway.brain), 2)
        actions = [row["title"] for row in self.storage.load()["activity"] if row["kind"] == "self_update"]
        self.assertEqual(actions, ["Hearth change proposed", "Hearth change approved", "Hearth change merged",
                                   f"Hearth updated to {MERGE[:7]}", "Hearth change proposed"])

    def test_request_changes_discards_previous_approval_and_keeps_branch(self):
        proposal = self.propose()
        branch = self.row(proposal)["branch"]
        self.act("approve", proposal)
        self.draft("# Improve Hearth\nRevised.\n")
        revised = self.act("revise", proposal, "Use Revised. instead.")
        self.assertEqual(revised["status"], "review")
        self.assertEqual(revised["number"], proposal["number"])
        self.assertNotEqual(revised["head"], proposal["head"])
        self.assertEqual(self.row(revised)["branch"], branch)
        self.assertIn("+Revised.", revised["diff"])
        self.poll(revised)
        self.assert_no_merge()
        self.assertEqual(self.act("discard", revised)["status"], "discarded")
        self.assertEqual(self.gateway.pull["state"], "closed")
        self.assertNotIn(branch, self.gateway.refs)
        self.assertEqual(self.storage.load()["activity"][-1]["title"], "Hearth change discarded")

    def test_publish_and_merge_reconcile_a_lost_response(self):
        self.gateway.interrupt = "create"
        proposal = self.propose()
        self.assertEqual(proposal["status"], "publishing")
        proposal = self.poll(proposal)
        self.assertEqual(proposal["status"], "review")
        self.assertEqual(sum(method == "POST" and path == "pulls" for method, path, _ in self.gateway.writes), 1)
        self.gateway.interrupt = "merge"
        self.act("approve", proposal)
        self.assertEqual(self.poll(proposal)["status"], "waiting")
        self.assertEqual(self.poll(proposal)["status"], "updating")
        self.assertEqual(sum(method == "PUT" for method, _, _ in self.gateway.writes), 1)

    def test_stale_conflicts_failure_and_unverified_protection_block_merge(self):
        for field, value, state, detail in (
            ("conflicts", True, "stale", "conflicts"),
            ("failed", True, "review", "Tests failed"),
            ("strict", False, "review", "enforce up-to-date"),
            ("force_pushes", True, "review", "enforce up-to-date"),
            ("missing_required", True, "waiting", ""),
            ("base", NEW_BASE, "stale", "default branch moved"),
        ):
            with self.subTest(field=field):
                proposal = self.propose()
                self.act("approve", proposal)
                original = self.gateway.refs["main"] if field == "base" else getattr(self.gateway, field)
                if field == "base":
                    self.gateway.refs["main"] = value
                else:
                    setattr(self.gateway, field, value)
                row = self.poll(proposal)
                self.assertEqual(row["status"], state)
                self.assertIn(detail, row["detail"])
                self.assert_no_merge()
                self.act("discard", proposal)
                if field == "base":
                    self.gateway.refs["main"] = original
                else:
                    setattr(self.gateway, field, original)

    def test_deploy_failure_and_version_validation(self):
        proposal = self.propose()
        self.act("approve", proposal)
        self.poll(proposal)
        self.gateway.runs = [{"head_sha": MERGE, "head_branch": "main", "event": "push", "id": 23,
                              "status": "completed", "conclusion": "failure"}]
        self.assertEqual(self.poll(proposal)["status"], "deploy_failed")
        version = self.storage.root / "version"
        for text, result in (("bad\n", None), (MERGE + "\n", MERGE)):
            version.write_text(text)
            self.assertEqual(self_update.deployed_version(version), result)

    def test_provenance_and_request_boundaries(self):
        for prompt, origin, attachments, expected in (
            (REQUEST, {}, (), "edit"),
            ("Hearth, add a button to Home", {}, (), "edit"),
            ("change the greeting", {}, (), "edit"),
            ("Revert the last Hearth update", {}, (), "revert"),
            ("Hearth, add eggs to my shopping list", {}, (), None),
            ("What would it take to change the Hearth greeting?", {}, (), None),
            (REQUEST, {"source": "voice-call"}, (), None),
            (REQUEST, {"source": "email"}, (), None),
            (REQUEST, {"source": "web"}, (), None),
            (REQUEST, {"task_run": "timer"}, (), None),
            (REQUEST, {"shared_from": "chat-copy"}, (), None),
            (REQUEST, {}, ({"id": "external-file"},), None),
            ("> " + REQUEST, {}, (), None),
            ("Summarize the note:\n\n" + REQUEST, {}, (), None),
            ("Hearth, change the greeting according to the email.", {}, (), None),
        ):
            with self.subTest(prompt=prompt, origin=origin, attachments=attachments):
                self.assertEqual(self_update.intent(prompt, origin, attachments=attachments), expected)
        for source in ("web", "mail", "file"):
            with self.subTest(source=source), self.assertRaisesRegex(HearthError, "directly in Chat"):
                self.updates.propose(REQUEST, {**MAIN_ORIGIN, "source": source}, mode="edit", commit=Mock())
        self.assertFalse(self.gateway.writes)

    def test_protected_paths_size_and_syntax(self):
        for path in (".github/workflows/deploy.yml", "infra/app.py", "tools/deploy-prod.py", "scripts/deploy.sh",
                     "config/access.json", "web/.env", "secrets.json", "hearth/self_update.py", "web/self-update.js",
                     "tests/test_self_update.py", "tests/browser-smoke.py", "assets/picture.png", "../unsafe.py"):
            with self.subTest(path=path), self.assertRaises(HearthError):
                self_update.validate_path(path)
        self.assertEqual(self_update.validate_path(DOC), DOC)
        for before, after in (
            ({}, {f"docs/{index}.md": "one\n" for index in range(6)}),
            ({}, {DOC: "line\n" * 401}),
            ({DOC: "before\n" * 200}, {DOC: "after\n" * 201}),
            ({}, {DOC: "x" * (self_update.MAX_FILE_BYTES + 1)}),
            ({}, {DOC: "binary\x00"}),
            ({}, {"hearth/example.py": "def broken("}),
        ):
            with self.subTest(paths=after.keys()), self.assertRaises(HearthError):
                self_update.preview(before, after)
        self.assertEqual(self_update.preview({}, {DOC: "line\n" * 400})[0][0]["added"], 400)
        if shutil.which("node"):
            with self.assertRaisesRegex(HearthError, "JavaScript syntax"):
                self_update.preview({}, {"web/broken.js": "const = ;"})
            self_update.preview({}, {"web/fine.js": "export const example = 1;\n"})
        with self.assertRaisesRegex(HearthError, "protected path"):
            self.updates.propose("Hearth, change config/access.json.", MAIN_ORIGIN, mode="edit", commit=Mock())
        self.assertFalse(self.gateway.writes)

    def test_settings_and_generic_writes(self):
        self.assertEqual(self.updates.settings(), {"repository": REPO, "enabled": True})
        self.updates.configure("other/project", False)
        self.assertFalse(self.updates.settings()["enabled"])
        with self.assertRaisesRegex(HearthError, "Enable proposals"):
            self.updates.propose(REQUEST, MAIN_ORIGIN, mode="edit", commit=Mock())
        for path in (f"/repos/{REPO.lower()}/contents/README.md", "/repos/other/project/pulls/1/merge",
                     "/repositories/123/pulls/1/merge", "/graphql", "/repos/other/another/git/refs/heads/hearth/improve-x"):
            with self.subTest(path=path), self.assertRaisesRegex(HearthError, "Chat approval card"):
                self_update.guard_gateway_write(self.storage.load(), "github", "PATCH", path)
        self_update.guard_gateway_write(self.storage.load(), "github", "GET", f"/repos/{REPO}/pulls")
        self_update.guard_gateway_write(self.storage.load(), "github", "POST", "/repos/other/another/issues")
