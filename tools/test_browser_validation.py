"""实时校验路由：来源隔离、错误响应、请求清理与断开唤醒。"""
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ws_bridge import Hub


class Browser:
    role = "extension"

    def __init__(self, browser_id):
        self.info = {"browserId": browser_id}
        self.messages = []
        self.ready = threading.Event()

    def send_json(self, message):
        self.messages.append(message)
        self.ready.set()
        return True


class BrowserValidationTest(unittest.TestCase):
    def setUp(self):
        self.hub = Hub()
        self.chrome, self.edge = Browser("chrome"), Browser("edge")
        self.hub.add(self.chrome)
        self.hub.add(self.edge)
        self.target = {"browserId": "chrome", "tabId": 7, "frameId": 2, "documentId": "document-A"}

    def request(self):
        output = {}
        thread = threading.Thread(target=lambda: output.update(
            self.hub.request_browser(self.target, "validate", "//button", timeout=1)))
        thread.start()
        self.assertTrue(self.chrome.ready.wait(1))
        return thread, output, self.chrome.messages[-1]["requestId"]

    def test_only_capture_source_can_reply(self):
        thread, output, request_id = self.request()
        self.assertEqual(self.edge.messages, [])
        self.assertEqual(self.chrome.messages[0]["target"]["documentId"], "document-A")
        self.hub.browser_reply(self.edge, {"requestId": request_id, "result": {"ok": True, "count": 99}})
        self.assertTrue(thread.is_alive())
        self.hub.browser_reply(self.chrome, {"requestId": request_id, "result": {"ok": True, "count": 2}})
        thread.join(1)
        self.assertEqual(output, {"ok": True, "count": 2})
        self.assertEqual(self.hub._requests, {})

    def test_disconnect_unblocks_pending_request(self):
        thread, output, _ = self.request()
        self.hub.remove(self.chrome)
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertFalse(output["ok"])
        self.assertIn("断开", output["error"])
        self.assertEqual(self.hub._requests, {})

    def test_timeout_and_late_response_do_not_leak(self):
        result = self.hub.request_browser(self.target, "validate", "//button", timeout=.01)
        self.assertIn("超时", result["error"])
        self.assertEqual(self.hub._requests, {})
        self.hub.browser_reply(self.chrome, {"requestId": self.chrome.messages[-1]["requestId"],
                                             "result": {"ok": True}})
        self.assertEqual(self.hub._requests, {})

    def test_completed_reply_survives_immediate_disconnect(self):
        def send(message):
            self.hub.browser_reply(self.chrome, {"requestId": message["requestId"], "result": {"ok": True}})
            self.hub.remove(self.chrome)
            return True
        self.chrome.send_json = send
        self.assertEqual(self.hub.request_browser(self.target, "clear"), {"ok": True})
        self.assertEqual(self.hub._requests, {})

    def test_missing_or_ambiguous_source_never_broadcasts(self):
        self.assertFalse(self.hub.request_browser({}, "validate")["ok"])
        self.hub.add(Browser("chrome"))
        self.assertFalse(self.hub.request_browser(self.target, "validate")["ok"])
        self.assertEqual(self.chrome.messages, [])
        self.assertEqual(self.edge.messages, [])

    def test_bad_request_and_clear_action(self):
        for action, xpath in (("other", ""), ("validate", 123), ("validate", "x" * 16385)):
            self.assertFalse(self.hub.request_browser(self.target, action, xpath)["ok"])
        self.assertFalse(self.hub.request_browser(dict(self.target, tabId=True), "validate")["ok"])


if __name__ == "__main__":
    unittest.main()
