"""Offline HTTP contracts and real ledger lifecycle; no provider traffic or live data."""
import email.utils
import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

os.environ["AESOP_PROBE_OFFLINE"] = "1"
os.environ["AESOP_SIMULATED_ROUTE"] = "1"

from aesop_studio import ledger, perplexity_api as api, providers, researcher, research_routes
from aesop_studio.services import Services
from aesop_studio.store import Store
from aesop_studio.tasks import Supervisor, TERMINAL

MODEL = "fixture/model"
RATES = {"input": 2.0, "output": 8.0, "cache_read": 0.2, "cache_write": 3.0}
CATALOG = {"object": "list", "data": [{"id": MODEL, "pricing": {**RATES, "unit": "usd_per_1m_tokens"}}]}
USAGE = {"prompt_tokens": 9, "prompt_tokens_details": {"cached_tokens": 3}, "completion_tokens": 4}


def encoded(value):
    return io.BytesIO(json.dumps(value).encode())


def events(finish="stop", usage=USAGE, done=True):
    chunks = [{"choices": [{"delta": {"content": "A precise answer."}, "finish_reason": None}]},
              {"choices": [{"delta": {}, "finish_reason": finish}]}]
    if usage is not None:
        chunks.append({"choices": [], "usage": usage})
    wire = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
    return io.BytesIO((wire + ("data: [DONE]\n\n" if done else "")).encode())


class KeyTestCase(unittest.TestCase):
    def setUp(self):
        api._catalog.clear()
        self.keys = mock.patch.object(research_routes, "key", return_value="test-offline")
        self.key_lookup = self.keys.start()
        self.addCleanup(self.keys.stop)
        self.addCleanup(api._catalog.clear)


class PerplexityTest(KeyTestCase):
    def test_catalog_request_cache_refresh_and_key_change(self):
        with mock.patch.object(api, "_urlopen", side_effect=lambda *a, **k: encoded(CATALOG)) as http:
            self.assertEqual(api.catalog()[0]["id"], MODEL)
            api.catalog()
            self.assertEqual(http.call_count, 1)
            req = http.call_args.args[0]
            self.assertEqual(req.full_url, api.BASE_URL + "/models")
            self.assertEqual(req.get_method(), "GET")
            api.catalog(refresh=True)
            self.key_lookup.return_value = "test-another-key"
            api.catalog()
            self.assertEqual(http.call_count, 3)

    def test_unknown_model_and_unknown_price_fail_closed(self):
        with mock.patch.object(api, "_urlopen", return_value=encoded(CATALOG)):
            with self.assertRaises(api.ApiError):
                api.prices("made/up")
        api._catalog.clear()
        bad = {"data": [{"id": MODEL, "pricing": {"unit": "unknown", **RATES}}]}
        with mock.patch.object(api, "_urlopen", return_value=encoded(bad)):
            self.assertEqual(api.catalog(), [])

    def test_nonfinite_price_is_not_dispatchable(self):
        bad = {"data": [{"id": MODEL, "pricing": {"unit": "usd_per_1m_tokens", **RATES, "input": float("inf")}}]}
        with mock.patch.object(api, "_urlopen", return_value=encoded(bad)):
            self.assertEqual(api.catalog(), [])

    def test_reservation_uses_highest_input_rate_and_output_cap(self):
        cap = api.max_cost(MODEL, 100, 2000, RATES)
        self.assertGreaterEqual(cap, ((100 + 64) * 3 + 2000 * 8) / 1e6 * 1.1)
        with self.assertRaises(api.ApiError):
            api.max_cost(MODEL, 400001, 2000, RATES)
        with self.assertRaises(api.ApiError):
            api.max_cost(MODEL, 100, 16001, RATES)

    def test_cached_usage_is_discounted_and_invalid_usage_refused(self):
        self.assertAlmostEqual(api.actual_cost(MODEL, USAGE, RATES), (6 * 2 + 3 * .2 + 4 * 8) / 1e6, places=6)
        with self.assertRaises(api.ApiError):
            api.actual_cost(MODEL, {**USAGE, "prompt_tokens": 1}, RATES)

    def test_chat_wire_shape_and_final_usage_chunk(self):
        out = []
        with mock.patch.object(api, "_urlopen", return_value=events()) as http:
            result = api.stream("hello", MODEL, 17, out.append, threading.Event())
        req = http.call_args.args[0]
        self.assertEqual(req.full_url, api.BASE_URL + "/chat/completions")
        self.assertEqual(json.loads(req.data), {"model": MODEL, "messages": [{"role": "user", "content": "hello"}],
            "max_completion_tokens": 17, "stream": True, "stream_options": {"include_usage": True}})
        self.assertEqual("".join(out), "A precise answer.")
        self.assertEqual(result["usage"], USAGE)
        self.assertEqual(result["status"], "completed")

    def test_cutoff_or_missing_usage_never_settles(self):
        for kwargs in ({"finish": "length"}, {"done": False}, {"usage": None}):
            with self.subTest(kwargs=kwargs), mock.patch.object(api, "_urlopen", return_value=events(**kwargs)):
                result = api.stream("hi", MODEL, 17, lambda d: None, threading.Event())
                self.assertIsNone(result["usage"])

    def test_cancel_before_and_after_send(self):
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(api, "_urlopen") as http:
            self.assertEqual(api.stream("hi", MODEL, 17, lambda d: None, cancel)["status"], "cancelled_presend")
            http.assert_not_called()
        cancel.clear()
        with mock.patch.object(api, "_urlopen", return_value=events()):
            result = api.stream("hi", MODEL, 17, lambda d: cancel.set(), cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["usage"])

    def test_stream_does_not_retry_network_failure(self):
        with mock.patch.object(api, "_urlopen", side_effect=OSError("offline")) as http:
            with self.assertRaises(api.ApiError):
                api.stream("hi", MODEL, 17, lambda d: None, threading.Event())
            self.assertEqual(http.call_count, 1)

    def test_deadline_returns_promptly_and_stops_late_deltas(self):
        class Slow(io.BytesIO):
            def __iter__(self):
                time.sleep(.3)
                yield b'data: {"choices":[{"delta":{"content":"late"}}]}\n'
        out = []
        with mock.patch.object(api, "_urlopen", return_value=Slow()):
            start = time.monotonic()
            result = api.stream("hi", MODEL, 17, out.append, threading.Event(), timeout=.01)
            self.assertEqual(result["status"], "deadline")
            self.assertLess(time.monotonic() - start, .25)
            time.sleep(.35)
            self.assertEqual(out, [])

    def test_multiple_choices_fail_without_retry(self):
        wire = b'data: {"choices":[{},{}]}\n\n'
        with mock.patch.object(api, "_urlopen", return_value=io.BytesIO(wire)) as http:
            with self.assertRaisesRegex(api.ApiError, "multiple choices"):
                api.stream("hi", MODEL, 17, lambda d: None, threading.Event())
            self.assertEqual(http.call_count, 1)

    def test_retry_after_is_honored_once_and_counts_attempts(self):
        error = urllib.error.HTTPError(api.BASE_URL, 429, "limited", {"Retry-After": "2"}, io.BytesIO())
        cancel = mock.Mock()
        cancel.is_set.return_value = False
        cancel.wait.return_value = False
        on_attempt = mock.Mock()
        with mock.patch.object(api, "_urlopen", side_effect=[error, encoded({})]) as http:
            with api.response(urllib.request.Request(api.BASE_URL), cancel=cancel, on_attempt=on_attempt):
                pass
        cancel.wait.assert_called_once_with(2)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(on_attempt.call_count, 2)
        date = email.utils.formatdate(time.time() + 10, usegmt=True)
        self.assertGreater(api.retry_after(date), 8)

    def test_long_retry_after_is_never_shortened(self):
        error = urllib.error.HTTPError(api.BASE_URL, 429, "limited", {"Retry-After": "100"}, io.BytesIO())
        with mock.patch.object(api, "_urlopen", side_effect=error) as http:
            with self.assertRaisesRegex(api.ApiError, "HTTP 429"):
                api.response(urllib.request.Request(api.BASE_URL), timeout=1)
            self.assertEqual(http.call_count, 1)

    def test_auth_and_tier_errors_are_sanitized_without_retry(self):
        for code in (400, 401, 402):
            error = urllib.error.HTTPError(api.BASE_URL, code, "rejected", {}, io.BytesIO(b"private details"))
            with self.subTest(code=code), mock.patch.object(api, "_urlopen", side_effect=error) as http:
                with self.assertRaisesRegex(api.ApiError, f"HTTP {code}") as exc:
                    api.catalog()
                self.assertNotIn("private", str(exc.exception))
                self.assertEqual(http.call_count, 1)

    def test_bearer_redirects_refused_and_child_key_stripped(self):
        self.assertIsNone(api._NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.org"))
        self.assertIn("PERPLEXITY_API_KEY", providers.BILLING_ENV)


class SearchTest(unittest.TestCase):
    def test_batch_wire_filters_dedup_and_dates(self):
        results = [{"url": "https://example.org/a", "title": "A", "date": "2026-10-01", "last_updated": "2026-10-25"},
                   {"url": "https://example.org/a", "title": "duplicate"}, {"url": "https://example.org/b"}]
        with mock.patch.object(researcher, "_key", return_value="test-offline"), \
             mock.patch.object(api, "_urlopen", return_value=encoded({"results": results})) as http:
            out = researcher._search("perplexity", ["first angle", "second angle"], max_results=20, country="us",
                search_domain_filter=["example.org"], search_language_filter=["en"], search_recency_filter="week",
                search_after_date_filter="10/01/2026", last_updated_before_filter="10/26/2026", max_tokens=1000)
        body = json.loads(http.call_args.args[0].data)
        self.assertEqual(body["query"], ["first angle", "second angle"])
        self.assertEqual(body["country"], "US")
        self.assertEqual(body["max_results"], 20)
        self.assertEqual(body["search_language_filter"], ["en"])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["last_updated"], "2026-10-25")
        self.assertEqual(out[0]["date"], "2026-10-01")

    def test_invalid_options_do_not_send(self):
        for query, opts in [([], {}), (["q"] * 6, {}), (["q", ""], {}), ("q", {"max_results": 21}),
                ("q", {"max_results": True}), ("q", {"country": "USA"}), ("q", {"search_language_filter": ["eng"]}),
                ("q", {"search_after_date_filter": "02/30/2026"}), ("q", {"search_context_size": "high"}),
                ("q", {"search_domain_filter": ["example.org", "-example.com"]})]:
            with self.subTest(query=query, opts=opts), mock.patch.object(api, "_urlopen") as http:
                with self.assertRaises(ValueError):
                    researcher._search("perplexity", query, **opts)
                http.assert_not_called()

    def test_firecrawl_batch_remains_first_and_merges_urls(self):
        with mock.patch.object(researcher, "_key", return_value="test-offline"), \
             mock.patch.object(researcher, "_post", return_value={"data": {"web": [{"url": "https://example.org"}]}}) as post:
            result = researcher._search("firecrawl", ["one", "two"])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(result), 1)

    def test_query_redaction(self):
        self.assertNotIn("pplx-", json.dumps(researcher.search_body(["find pplx-abcdefghijklmnopqrstuvwx", "other"])))

    def test_documented_domain_tld_and_path_filters(self):
        domains = [".gov", "example.org/research"]
        self.assertEqual(researcher.search_body("q", search_domain_filter=domains)["search_domain_filter"], domains)


class LedgerLifecycleTest(KeyTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="aesop-perplexity-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "project").mkdir()
        self.store = Store(root / "data")
        self.addCleanup(self.store.close)
        store = self.store
        workers = []

        class Worker(threading.Thread):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                workers.append(self)

            def run(self):
                try:
                    super().run()
                finally:
                    store.close()  # Store connections belong to the thread that opened them.

        def join_workers():
            for worker in workers:
                worker.join(5)
                self.assertFalse(worker.is_alive(), "offline worker did not stop before store cleanup")

        threads = mock.patch.object(threading, "Thread", Worker)
        threads.start()
        self.addCleanup(threads.stop)
        self.addCleanup(join_workers)
        self.join_workers = join_workers
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        route = {"provider": "perplexity", "route_type": "api", "state": "READY_METERED_DISABLED",
                 "auth_status": "api_key_present", "billing_basis": "metered", "supported_modes": ["chat"],
                 "incremental_cost_status": "metered; catalog rates"}
        self.store.x("INSERT INTO kv(k,v) VALUES('routes',?)", (json.dumps({"perplexity-orchestrator": route}),))
        self.p = self.svc.create_project("Offline", str(root / "project"), "perplexity-orchestrator")
        self.p = self.svc.update_project(self.p["id"], {"model": MODEL})
        self.c = self.svc.new_conversation(self.p["id"])

    def send(self):
        out = self.svc.send(self.p["id"], self.c["id"], "hello", [], None)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            task = self.sup.get(out["task_id"])
            if task["state"] in TERMINAL:
                self.join_workers()  # Terminal state can precede the worker's final Store access.
                return task
            time.sleep(.02)
        self.fail("offline task did not terminate")

    def test_disabled_route_sends_nothing(self):
        with mock.patch.object(api, "_urlopen") as http:
            self.assertEqual(self.send()["state"], "BLOCKED_OWNER")
            http.assert_not_called()

    def test_runtime_and_mission_reserve_before_send_and_settle(self):
        for mission in (False, True):
            with self.subTest(mission=mission):
                ledger.set_runtime_limit(self.store, 1)
                ledger.set_permit(self.store, mission)
                def respond(req, **kwargs):
                    if req.full_url.endswith("/models"):
                        return encoded(CATALOG)
                    row = self.store.one("SELECT * FROM ledger ORDER BY created DESC LIMIT 1")
                    self.assertEqual(row["status"], "reserved")
                    self.assertEqual(row["purpose"], "mission" if mission else "runtime")
                    return events()
                with mock.patch.object(api, "_urlopen", side_effect=respond):
                    task = self.send()
                self.assertEqual(task["state"], "COMPLETED", task["error"])
                row = self.store.one("SELECT * FROM ledger WHERE task_ref=?", (task["id"],))
                self.assertEqual(row["status"], "settled")
                self.assertAlmostEqual(row["settled_usd"], api.actual_cost(MODEL, USAGE, RATES))
                self.assertIn("2026-10-26", row["price_source"])

    def test_output_cap_keeps_reservation(self):
        ledger.set_runtime_limit(self.store, 1)
        with mock.patch.object(api, "_urlopen", side_effect=lambda req, **k:
                               encoded(CATALOG) if req.full_url.endswith("/models") else events(finish="length")):
            task = self.send()
        self.assertEqual(task["state"], "EFFECT_UNKNOWN")
        self.assertEqual(self.store.one("SELECT status FROM ledger WHERE task_ref=?", (task["id"],))["status"], "ambiguous")

    def test_limit_blocks_before_chat_send(self):
        # Limits are stored in cents: .0001 disables the route before catalog lookup.
        for limit, cached, catalog_calls in ((.0001, False, 0), (.01, False, 1), (.01, True, 0)):
            with self.subTest(limit=limit, cached=cached):
                api._catalog.clear()
                ledger.set_runtime_limit(self.store, limit)
                with mock.patch.object(api, "_urlopen", return_value=encoded(CATALOG)) as http:
                    if cached:
                        api.catalog()
                        http.reset_mock()
                    task = self.send()
                    self.assertEqual(task["state"], "BLOCKED_OWNER")
                    self.assertIn("ceiling" if ledger.runtime_limit(self.store) else "disabled", task["error"].lower())
                    self.assertEqual(http.call_count, catalog_calls)
                    self.assertTrue(all(call.args[0].get_method() == "GET" for call in http.call_args_list))
                self.assertEqual(self.store.q("SELECT id FROM ledger"), [])

    def test_cancelled_stream_keeps_reservation(self):
        ledger.set_runtime_limit(self.store, 1)
        with mock.patch.object(api, "catalog", return_value=CATALOG["data"]), \
             mock.patch.object(api, "stream", return_value={"text": "partial", "usage": None, "status": "cancelled"}):
            task = self.send()
        self.assertEqual(task["state"], "CANCELLED")
        self.assertEqual(self.store.one("SELECT status FROM ledger WHERE task_ref=?", (task["id"],))["status"], "ambiguous")

    def test_invalid_search_does_not_take_quota(self):
        result = researcher.research(self.store, ["q"] * 6)
        self.assertFalse(result["ok"])
        self.assertEqual(researcher.daily_used(self.store), 0)

    def test_search_retry_cannot_cross_daily_cap(self):
        for _ in range(researcher.DAILY_CAP - 1):
            researcher._bump(self.store)
        err = urllib.error.HTTPError("https://api.perplexity.ai/search", 429, "limited", {"Retry-After": "0"}, io.BytesIO())
        with mock.patch.object(researcher, "backends", return_value=["perplexity"]), \
             mock.patch.object(researcher, "_key", return_value="test-offline"), \
             mock.patch.object(api, "_urlopen", side_effect=err) as http:
            result = researcher.research(self.store, ["one", "two"])
        self.assertFalse(result["ok"])
        self.assertEqual(researcher.daily_used(self.store), researcher.DAILY_CAP)
        self.assertEqual(http.call_count, 1)
