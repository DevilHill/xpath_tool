"""HTTP 边界、定位唯一性及错误语义回归；不启动用户浏览器。"""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from wbot import web
from wbot.errors import (AmbiguousElementError, BridgeConnectionError,
    ElementNotFoundError, InvalidSelectorError, StaleTargetError,
    UnsupportedFeatureError, WbotError, WbotTimeoutError)
from wbot.web.browser import BridgeClient


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.server.redirect:
            self.send_response(302)
            self.send_header("Location", "http://192.0.2.1/")
            self.end_headers()
        else:
            self.send({"ok": True, "payload": self.server.payload})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.commands.append(data)
        if self.server.error:
            self.send({"ok": False, **self.server.error})
            return
        action, options = data["action"], data["options"]
        count = self.server.count
        if action == "query":
            self.send({"ok": True, "result": {"count": count, "items": []}})
        elif options.get("strict") and count > 1:
            self.send({"ok": False, "code": "ambiguous", "error": "multiple"})
        elif options.get("index", 0) >= count:
            self.send({"ok": False, "code": "not_found", "error": "absent"})
        else:
            result = {"text": "你好", "attribute": "value", "visible": True, "enabled": True}.get(action, True)
            self.send({"ok": True, "result": result})


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), BridgeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.server.count = 1
        self.server.error = None
        self.server.redirect = False
        self.server.commands = []
        self.server.payload = {"browserId": "b1", "title": "Fixture", "frame": {
            "tabId": 3, "frameId": 0, "documentId": "current", "url": "https://test.invalid/",
            "topUrl": "https://test.invalid/", "isTop": True, "xpathScope": "page"}}
        self.browser = web.attach(self.base)

    def test_get_and_attach_metadata(self):
        result = web.get(url="https://test.invalid/", title="Fixture", base_url=self.base)
        self.assertEqual(result.target["documentId"], "current")
        self.assertEqual(result.get_title(), "Fixture")
        with self.assertRaises(StaleTargetError):
            web.get(title="other", base_url=self.base)

    def test_remote_and_credentials_are_rejected(self):
        for url in ("https://127.0.0.1", "http://localhost", "http://example.org", "http://127.0.0.1/a", "http://user@127.0.0.1", "http://127.0.0.1?x=1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                BridgeClient(url)

    def test_redirect_is_rejected(self):
        self.server.redirect = True
        with self.assertRaises(BridgeConnectionError):
            web.attach(self.base)

    def test_no_pick_raises_diagnostic(self):
        self.server.payload = None
        with self.assertRaises(StaleTargetError):
            web.attach(self.base)

    def test_unique_find_and_action_envelope(self):
        element = self.browser.find("//button", timeout=0)
        self.assertTrue(element.click())
        command = self.server.commands[-1]
        self.assertEqual(command["action"], "click")
        self.assertEqual(command["options"], {"index": 0, "strict": True})
        self.assertEqual(command["target"]["documentId"], "current")

    def test_ambiguous_find_does_not_click(self):
        self.server.count = 2
        with self.assertRaises(AmbiguousElementError):
            self.browser.find("//button", timeout=1)
        self.assertEqual([x["action"] for x in self.server.commands], ["query"])

    def test_action_rechecks_uniqueness_after_dom_change(self):
        element = self.browser.find("//button", timeout=0)
        self.server.count = 2
        with self.assertRaises(AmbiguousElementError):
            element.click()

    def test_find_all_explicit_index(self):
        self.server.count = 3
        elements = self.browser.find_all("//button", timeout=0)
        self.assertEqual(len(elements), 3)
        elements[2].click()
        self.assertEqual(self.server.commands[-1]["options"], {"index": 2, "strict": False})

    def test_find_all_rejects_truncation(self):
        self.server.count = 501
        with self.assertRaises(WbotError):
            self.browser.find_all("//*", timeout=0)

    def test_empty_find_and_wait(self):
        self.server.count = 0
        with self.assertRaises(ElementNotFoundError):
            self.browser.find("//missing", timeout=0)
        self.assertEqual(self.browser.find_all("//missing", timeout=0), [])
        self.assertFalse(self.browser.wait_appear("//missing", timeout=0))
        self.assertTrue(self.browser.wait_disappear("//missing", timeout=0))

    def test_invalid_timeout(self):
        for value in (-1, float("nan"), float("inf"), True, "5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.browser.find("//button", timeout=value)

    def test_error_codes_not_retried(self):
        for code, error in (("stale_target", StaleTargetError), ("invalid_selector", InvalidSelectorError), ("disconnected", BridgeConnectionError)):
            self.server.error = {"code": code, "error": "failure"}
            self.server.commands.clear()
            with self.assertRaises(error):
                self.browser.find("//button", timeout=5)
            self.assertEqual(len(self.server.commands), 1)

    def test_saved_document_id_is_not_reused(self):
        record = {"xpath": "//button", "url": "https://test.invalid/", "frame": {
            "frameId": 0, "documentId": "previous-session"}}
        self.browser.find(record, timeout=0).click()
        self.assertEqual(self.server.commands[-1]["target"]["documentId"], "current")

    def test_scope_mismatch_never_dispatches(self):
        for record in ({"xpath": "//button", "url": "https://different.invalid/"},
                       {"xpath": "//button", "frame": {"frameId": 4}}):
            with self.assertRaises(StaleTargetError):
                self.browser.find(record, timeout=0)
        self.assertEqual(self.server.commands, [])

    def test_callable_selector_xpath(self):
        class Selector:
            def xpath(self):
                return "//button"
        self.assertEqual(self.browser.find(Selector(), timeout=0).xpath, "//button")

    def test_input_options_and_validation(self):
        element = self.browser.find("//input", timeout=0)
        element.input("新值", append=True)
        self.assertEqual(self.server.commands[-1]["options"]["value"], "新值")
        self.assertTrue(self.server.commands[-1]["options"]["append"])
        with self.assertRaises(TypeError):
            element.input(1)
        with self.assertRaises(UnsupportedFeatureError):
            element.input("x", simulative=True)

    def test_text_attributes_and_states(self):
        element = self.browser.find("//input", timeout=0)
        self.assertEqual(element.get_text(), "你好")
        self.assertEqual(element.get_value(), "value")
        self.assertTrue(element.is_visible())
        self.assertTrue(element.is_enabled())
        self.assertIs(element.wait("visible", timeout=0), element)
        self.assertIs(element.wait("attached", timeout=0), element)

    def test_element_wait_timeout_and_missing(self):
        element = self.browser.find("//input", timeout=0)
        with self.assertRaises(WbotTimeoutError):
            element.wait("hidden", timeout=0)
        self.server.count = 0
        self.assertFalse(element.exists())
        self.assertFalse(element.is_visible())
        self.assertIs(element.wait("detached", timeout=0), element)

    def test_check_select_and_scroll(self):
        element = self.browser.find("//input", timeout=0)
        element.check("uncheck")
        self.assertIs(self.server.commands[-1]["options"]["value"], False)
        element.select("标签", mode="text")
        self.assertEqual(self.server.commands[-1]["options"]["mode"], "text")
        self.assertTrue(element.scroll_into_view())
        with self.assertRaises(UnsupportedFeatureError):
            element.select("x", mode="fuzzy")

    def test_target_is_defensive_copy(self):
        target = self.browser.target
        target["documentId"] = "changed"
        self.assertEqual(self.browser.target["documentId"], "current")

    def test_unsupported_capability_explicit(self):
        with self.assertRaises(UnsupportedFeatureError):
            self.browser.navigate("https://test.invalid/")
        with self.assertRaises(UnsupportedFeatureError):
            self.browser.find_by_css("button")
        with self.assertRaises(UnsupportedFeatureError):
            web.get(mode="cef", base_url=self.base)

    def test_optional_backend_has_install_diagnostic(self):
        with patch.dict(sys.modules, {"playwright.sync_api": None}):
            with self.assertRaisesRegex(UnsupportedFeatureError, "wbot\\[web\\]"):
                web.create()


if __name__ == "__main__":
    unittest.main()
