"""End-to-end transport checks for the Lab 11 localhost API."""

import http.client
import hashlib
import json
import threading
import unittest
from pathlib import Path

from lab11.search import ApiError, SearchService
from lab11.server import create_server


class FixedService:
    """Small deterministic service double that keeps these tests about HTTP transport."""

    max_body_bytes = 40
    host = "127.0.0.1"
    port = 0

    def search(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise ApiError(400, "object_required")
        query = payload.get("query")
        if not isinstance(query, str):
            raise ApiError(400, "query_must_be_string")
        if not query.strip():
            raise ApiError(400, "empty_query")
        return {
            "status": "ok",
            "model": "tfidf",
            "results": [{"id": "P001", "score": 0.5}],
            "human_decision_required": True,
        }

    def get_image(self, poster_id: str):
        if poster_id == "P001":
            return b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        if poster_id == "P503":
            raise ApiError(503, "catalog_unavailable")
        raise ApiError(404, "poster_not_found")


class ServerTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = create_server(FixedService())
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        cls.httpd.server_close()

    def request(self, method: str, path: str, body: bytes = b"", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def search(self, raw: bytes, content_type: str = "application/json"):
        status, headers, body = self.request(
            "POST", "/search", raw, {"Content-Type": content_type, "Content-Length": str(len(raw))}
        )
        return status, headers, json.loads(body)

    def search_without_content_length(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.putrequest("POST", "/search")
            connection.putheader("Content-Type", "application/json")
            connection.endheaders()
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_search_returns_a_structured_result(self) -> None:
        status, headers, body = self.search('{"query":"джаз"}'.encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["results"][0]["id"], "P001")

    def test_search_uses_structured_errors(self) -> None:
        cases = (
            (b"{", "application/json", 400, "invalid_json"),
            (b'{"query":"x","extra":NaN}', "application/json", 400, "invalid_json"),
            (b"[]", "application/json", 400, "object_required"),
            (b'{"query":""}', "application/json", 400, "empty_query"),
            (b'{"query":"x"}', "text/plain", 415, "unsupported_media_type"),
            (b"x" * 41, "application/json", 413, "body_too_large"),
        )
        for raw, content_type, expected_status, expected_error in cases:
            with self.subTest(error=expected_error):
                status, _, body = self.search(raw, content_type)
                self.assertEqual(status, expected_status)
                self.assertEqual(body, {
                    "error": expected_error,
                    "results": [],
                    "status": "error",
                })

    def test_search_rejects_a_missing_content_length(self) -> None:
        status, body = self.search_without_content_length()
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_content_length")

    def test_images_are_addressed_only_by_poster_identifier(self) -> None:
        status, headers, body = self.request("GET", "/posters/P001")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/svg+xml")
        self.assertTrue(body.startswith(b"<svg"))

        status, _, body = self.request("GET", "/posters/../../etc/passwd")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_unknown_and_unavailable_resources_are_distinct(self) -> None:
        status, _, body = self.request("GET", "/posters/UNKNOWN")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "poster_not_found")

        status, _, body = self.request("GET", "/posters/P503")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {
            "error": "catalog_unavailable",
            "results": [],
            "status": "unavailable",
        })

    def test_unknown_routes_return_json_404(self) -> None:
        status, headers, body = self.request("GET", "/other")
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body)["error"], "not_found")


class LoadedServiceTransportTests(unittest.TestCase):
    """Check that the HTTP adapter also works with the reproducible local service."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = create_server(SearchService.load(), port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        cls.httpd.server_close()

    def request(self, method: str, path: str, body: bytes = b"", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_search_result_links_to_a_verified_local_svg(self) -> None:
        request = json.dumps({"query": "лаконичный"}).encode("utf-8")
        status, body = self.request(
            "POST", "/search", request,
            {"Content-Type": "application/json", "Content-Length": str(len(request))},
        )
        self.assertEqual(status, 200)
        result = json.loads(body)["results"][0]

        status, image = self.request("GET", result["image"])
        self.assertEqual(status, 200)
        catalog = json.loads(
            (Path(__file__).resolve().parents[1] / "lab06" / "data" / "clean.json").read_bytes()
        )
        expected = next(row["sha256"] for row in catalog if row["id"] == result["id"])
        self.assertEqual(hashlib.sha256(image).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
