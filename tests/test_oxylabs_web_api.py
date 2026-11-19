"""Retry and error-mapping tests for the vendored Oxylabs Web API client.

The client under test ships with the `oxylabs-web-api` skill
(.agents/skills/oxylabs-web-api/scripts/web_api.py). These tests drive it
against a mocked transport -- urllib.request.urlopen is replaced, so no
network call and no API key are ever used.

Per the integration checklist, the tests set a dummy key of their own, so a
failing assertion prints that and never a real credential.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

DUMMY_KEY = "test-dummy-key-not-a-real-credential"

CLIENT_PATH = (
    Path(__file__).resolve().parent.parent
    / ".agents"
    / "skills"
    / "oxylabs-web-api"
    / "scripts"
    / "web_api.py"
)


def load_client():
    """Load web_api.py by path: its directory is not an importable package."""
    spec = importlib.util.spec_from_file_location("oxylabs_web_api", CLIENT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load client from {CLIENT_PATH}")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict("os.environ", {"OXYLABS_WEB_API_KEY": DUMMY_KEY}):
        spec.loader.exec_module(module)
    return module


def http_error(code: int, body: str = "{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://webapi.oxylabs.io/v1/search",
        code=code,
        msg=f"HTTP {code}",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body.encode()),
    )


def ok_response(payload: dict):
    """A urlopen context manager returning payload as JSON."""
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    ctx = mock.MagicMock()
    ctx.__enter__.return_value = resp
    ctx.__exit__.return_value = False
    return ctx


class ClientTestCase(unittest.TestCase):
    """Base: a loaded client, a dummy key in the environment, and no real sleeping."""

    def setUp(self) -> None:
        self.client = load_client()
        env = mock.patch.dict("os.environ", {"OXYLABS_WEB_API_KEY": DUMMY_KEY})
        env.start()
        self.addCleanup(env.stop)
        # Retries sleep with jitter; keep the suite fast and deterministic.
        sleep = mock.patch.object(self.client.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def call(self, side_effect):
        """Run client.call with urlopen mocked; returns (result_or_exc, mock).

        die() writes its message to stderr and raises SystemExit(code), so the
        message is captured here rather than read off the exception.
        """
        buf = io.StringIO()
        with mock.patch.object(
            self.client.urllib.request, "urlopen", side_effect=side_effect
        ) as opener:
            with contextlib.redirect_stderr(buf):
                try:
                    result = self.client.call("/v1/search", {"query": "x"})
                except SystemExit as exc:
                    result = exc
        self.err = buf.getvalue()
        return result, opener


class TestRetry(ClientTestCase):
    def test_500_then_success_returns_body(self):
        result, opener = self.call([http_error(500), ok_response({"state": "done"})])
        self.assertEqual(result, {"state": "done"})
        self.assertEqual(opener.call_count, 2, "a 500 should be retried once, then succeed")
        self.assertEqual(self.sleep.call_count, 1, "the retry should back off before retrying")

    def test_retryable_status_exhausts_at_max_attempts(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                result, opener = self.call([http_error(status)] * 4)
                self.assertIsInstance(result, SystemExit)
                self.assertEqual(
                    opener.call_count,
                    self.client.MAX_ATTEMPTS,
                    f"{status} should be tried exactly MAX_ATTEMPTS times",
                )

    def test_transport_error_is_retried_then_surfaced(self):
        result, opener = self.call([urllib.error.URLError("connection reset")] * 4)
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(opener.call_count, self.client.MAX_ATTEMPTS)
        self.assertIn("Could not reach", self.err)

    def test_transport_error_then_success(self):
        result, opener = self.call(
            [urllib.error.URLError("reset"), ok_response({"state": "done"})]
        )
        self.assertEqual(result, {"state": "done"})
        self.assertEqual(opener.call_count, 2)


class TestErrorMapping(ClientTestCase):
    def test_401_is_not_retried(self):
        result, opener = self.call([http_error(401, '{"title":"UNAUTHORIZED"}')] * 4)
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(opener.call_count, 1, "401 is a credential problem; retrying cannot help")
        self.assertIn("401", self.err)

    def test_400_validation_is_not_retried(self):
        body = json.dumps(
            {
                "status": 400,
                "title": "VALIDATION_ERROR",
                "errors": [
                    {"pointer": "#/max_results", "detail": "Input should be <= 20"}
                ],
            }
        )
        result, opener = self.call([http_error(400, body)] * 4)
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(opener.call_count, 1, "400 must never be retried unchanged")
        self.assertIn("max_results", self.err, "the offending field should be surfaced")

    def test_429_quota_exceeded_stops_immediately(self):
        body = '{"title":"QUOTA_EXCEEDED","detail":"quota spent"}'
        result, opener = self.call([http_error(429, body)] * 4)
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(
            opener.call_count, 1, "a spent quota is not transient; it should not be retried"
        )

    def test_429_rate_limit_is_retried(self):
        body = '{"title":"RATE_LIMITED","detail":"slow down"}'
        result, opener = self.call([http_error(429, body)] * 4)
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(opener.call_count, self.client.MAX_ATTEMPTS)

    def test_2xx_with_faulted_envelope_is_an_error(self):
        result, opener = self.call([ok_response({"status": "faulted", "title": "REQUEST_FAILED"})])
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(opener.call_count, 1)
        self.assertIn("faulted", self.err)

    def test_408_is_not_retried_documented_deviation(self):
        """The published error table says retry 408 with backoff.

        RETRY_STATUSES in the vendored client omits 408, so a server-side scrape
        timeout fails on the first attempt. This test pins the client's ACTUAL
        behaviour so the gap is visible rather than silent; flip it if the
        vendored script is updated to match the documented rules.
        """
        self.assertNotIn(408, self.client.RETRY_STATUSES)
        result, opener = self.call([http_error(408)] * 4)
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(opener.call_count, 1)


class TestCredentialHandling(ClientTestCase):
    def test_missing_key_exits_without_calling_out(self):
        with mock.patch.dict("os.environ", {"OXYLABS_WEB_API_KEY": ""}):
            with mock.patch.object(self.client.urllib.request, "urlopen") as opener:
                with self.assertRaises(SystemExit) as caught:
                    self.client.call("/v1/search", {"query": "x"})
        self.assertEqual(caught.exception.code, 2)
        opener.assert_not_called()

    def test_bearer_header_is_sent(self):
        with mock.patch.object(
            self.client.urllib.request, "urlopen", side_effect=[ok_response({"ok": True})]
        ) as opener:
            self.client.call("/v1/search", {"query": "x"})
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {DUMMY_KEY}")
        self.assertEqual(request.get_header("Content-type"), "application/json")


if __name__ == "__main__":
    unittest.main()
