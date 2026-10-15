"""可选浏览器真实集成：仅访问本测试生成的本机 HTML。"""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from wbot import web
from wbot.errors import (AmbiguousElementError, ElementNotFoundError,
    InvalidSelectorError, StaleTargetError)


@unittest.skipUnless(importlib.util.find_spec("playwright"), "未安装可选 playwright 依赖")
class PlaywrightIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="wbot-browser-fixture-")
        cls.fixture = Path(cls.temp.name) / "fixture.html"
        cls.next_fixture = Path(cls.temp.name) / "next.html"
        cls.fixture.write_text("""<!doctype html><meta charset='utf-8'><title>wbot fixture</title>
            <button id='click' onclick="this.textContent='已点击'">点击</button>
            <input id='input'><input id='checkbox' type='checkbox'>
            <select id='select'><option value='a'>选项 A</option><option value='b'>选项 B</option></select>
            <button class='duplicate'>first</button><button class='duplicate'>second</button>
            <div id='hidden' style='display:none'>hidden</div>
            <input id='disabled' disabled><div id='editable' contenteditable='true'>old</div>
            <div id='output'></div>""", encoding="utf-8")
        cls.next_fixture.write_text("""<!doctype html><title>next</title>
            <button id='click' onclick="this.textContent='wrong-page-clicked'">new-page</button>""", encoding="utf-8")
        executable = os.environ.get("WBOT_BROWSER_EXECUTABLE_PATH")
        options = {"headless": True}
        if executable:
            options["executable_path"] = executable
        try:
            cls.browser = web.create(cls.fixture.as_uri(), **options)
        except Exception:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls.temp.cleanup()

    def setUp(self):
        self.browser.navigate(self.fixture.as_uri())

    def test_create_click_input_select(self):
        self.assertEqual(self.browser.get_title(), "wbot fixture")
        button = self.browser.find("//*[@id='click']", timeout=0)
        button.click()
        self.assertEqual(button.get_text(), "已点击")
        field = self.browser.find("//*[@id='input']", timeout=0)
        field.input("中文")
        field.input("追加", append=True)
        self.assertEqual(field.get_value(), "中文追加")
        select = self.browser.find("//*[@id='select']", timeout=0)
        select.select("b")
        self.assertEqual(select.get_value(), "b")
        select.select("选项 A", mode="text")
        self.assertEqual(select.get_value(), "a")

    def test_strict_matching_and_explicit_index(self):
        with self.assertRaises(AmbiguousElementError):
            self.browser.find("//*[@class='duplicate']", timeout=0)
        elements = self.browser.find_all("//*[@class='duplicate']", timeout=0)
        self.assertEqual([e.get_text() for e in elements], ["first", "second"])
        element = self.browser.find("//*[@id='click']", timeout=0)
        self.browser.page.evaluate("() => document.body.append(document.querySelector('#click').cloneNode(true))")
        with self.assertRaises(AmbiguousElementError):
            element.click()

    def test_navigation_invalidates_existing_handle(self):
        element = self.browser.find("//*[@id='click']", timeout=0)
        self.browser.navigate(self.next_fixture.as_uri())
        with self.assertRaises(StaleTargetError):
            element.click()
        with self.assertRaises(StaleTargetError):
            element.exists()
        self.assertEqual(self.browser.find("//*[@id='click']", timeout=0).get_text(), "new-page")

    def test_saved_scope_and_invalid_xpath(self):
        with self.assertRaises(StaleTargetError):
            self.browser.find({"xpath": "//button", "url": self.next_fixture.as_uri()}, timeout=0)
        for xpath in ("count(//button)", "//button/@id", "//*[invalid"):
            with self.subTest(xpath=xpath), self.assertRaises(InvalidSelectorError):
                self.browser.find(xpath, timeout=0)
        with self.assertRaises(ElementNotFoundError):
            self.browser.find("//*[@id='missing']", timeout=0)

    def test_states_check_and_contenteditable(self):
        self.assertFalse(self.browser.find("//*[@id='hidden']", timeout=0).is_visible())
        self.assertFalse(self.browser.find("//*[@id='disabled']", timeout=0).is_enabled())
        checkbox = self.browser.find("//*[@id='checkbox']", timeout=0)
        checkbox.check()
        self.assertTrue(self.browser.page.locator("#checkbox").is_checked())
        checkbox.check("uncheck")
        self.assertFalse(self.browser.page.locator("#checkbox").is_checked())
        editable = self.browser.find("//*[@id='editable']", timeout=0)
        editable.input("new", append=True)
        self.assertEqual(editable.get_text(), "oldnew")


if __name__ == "__main__":
    unittest.main()
