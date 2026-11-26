import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.request import ProxyHandler, build_opener

from scripts.check_edge_auth import (
    NoRedirect,
    is_private_response,
    parse_base,
    parse_private_path,
    parse_share,
    probe,
)


class EdgeAuthParsingTests(unittest.TestCase):
    def test_base_is_an_http_origin_without_credentials(self):
        self.assertEqual(parse_base("https://workspace.example.test:8443/"),
                         "https://workspace.example.test:8443")
        for invalid in ("", "workspace.example.test", "file:///tmp/page",
                        "https://user:pass@workspace.example.test", "https://workspace.example.test:wrong",
                        "https://workspace.example.test/path", "https://workspace.example.test?",
                        "https://workspace.example.test/#", " https://workspace.example.test"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                parse_base(invalid)

    def test_private_paths_preserve_the_resource_and_query(self):
        artifact = "/api/artifacts/file?id=local%3Afixture&inline=1"
        page = "/pages/" + "a" * 32 + "/v/2?download=1"
        self.assertEqual(parse_private_path(artifact, artifact=True), artifact)
        self.assertEqual(parse_private_path(page, artifact=False), page)
        for value, is_artifact in (
            ("//other.example.test" + artifact, True), ("https://other.example.test" + page, False),
            ("/api/artifacts/file", True), ("/api/artifacts/file?id=", True),
            ("/api/artifacts/file?id=fixture&id=duplicate", True), (artifact + "#fragment", True),
            ("/api/state", True), ("/pages/" + "a" * 32 + "/v/0", False), ("/p/" + "a" * 43, False),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_private_path(value, artifact=is_artifact)

    def test_share_token_has_an_exact_path_and_no_query(self):
        origin = "https://pages.example.test"
        token = "aB_-" * 10 + "Z09"
        url = origin + "/p/" + token
        self.assertEqual(parse_share(url), (origin, token))
        for invalid in (url[:-1], url + "/", url + "?", url + "#", url + "%61", origin + "/p/",
                        "/p/" + token, url.replace("https://", "https://user@")):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                parse_share(invalid)

    def test_private_response_requires_401_or_redirect_with_location(self):
        url = "https://workspace.example.test/api/state"
        for status, location in ((401, None), (301, "/login"), (302, "https://login.example.test/"),
                                 (303, "/login"), (307, "/login"), (308, "/login")):
            with self.subTest(status=status, location=location):
                self.assertTrue(is_private_response(url, status, location))
        for status, location in ((200, "/login"), (304, "/login"), (403, None),
                                 (404, None), (500, None), (302, None), (302, "/api/state"),
                                 (302, "#same-resource"), (302, "file:///tmp/test"),
                                 (302, "https://user@other.example.test/"), (302, " \r\n")):
            with self.subTest(status=status, location=location):
                self.assertFalse(is_private_response(url, status, location))

    def test_probe_observes_the_first_response_and_sends_no_credentials(self):
        requests = []

        class Edge(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                requests.append((self.command, self.path, body, self.headers.get("Authorization"),
                                 self.headers.get("Cookie")))
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()

            def do_GET(self):
                requests.append((self.command, self.path))
                self.send_response(200)
                self.end_headers()

        with ThreadingHTTPServer(("127.0.0.1", 0), Edge) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/api/chat"
                status, headers = probe(build_opener(ProxyHandler({}), NoRedirect()), "POST", url)
                self.assertEqual((status, headers["Location"]), (302, "/login"))
                self.assertEqual(requests, [("POST", "/api/chat", b"{}", None, None)])
            finally:
                server.shutdown()
                thread.join()
