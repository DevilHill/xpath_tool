"""真实本机HTTP验证元素库、动作参数与跨站写保护。"""
import json
from pathlib import Path
import tempfile
import unittest
from urllib.request import build_opener, ProxyHandler, Request
from urllib.error import HTTPError
from unittest.mock import patch

from app import server


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.old = server.ELEMENTS_PATH
        server.ELEMENTS_PATH = Path(cls.temp.name) / 'elements.sqlite3'
        cls.httpd, cls.port = server.run_server(0)
        cls.base = f'http://127.0.0.1:{cls.port}'
        cls.client = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.ELEMENTS_PATH = cls.old
        cls.temp.cleanup()

    def call(self, path, body=None, **headers):
        req = Request(self.base + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json', **headers})
        try:
            with self.client.open(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def test_save_export_import_and_delete(self):
        status, result = self.call('/api/elements/save', {'record': {
            'name': '登录按钮', 'group': '测试', 'xpath': "//button[@id='login']"}})
        self.assertEqual(status, 200, result)
        item = result['item']
        _, listing = self.call('/api/elements')
        self.assertIn(item['id'], [x['id'] for x in listing['items']])
        _, exported = self.call('/api/elements/export')
        status, result = self.call('/api/elements/import', {'data': exported['data'], 'conflict': 'skip'})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['result']['skipped'], 1)
        self.assertTrue(self.call('/api/elements/delete', {'id': item['id']})[1]['deleted'])

    def test_invalid_import_does_not_succeed(self):
        self.assertEqual(self.call('/api/elements/save', {'record': {'name': '错误', 'xpath': 'count(//button)'}})[0], 400)
        self.assertEqual(self.call('/api/elements/import', {'data': {'unrecognized': []}})[0], 400)

    def test_cross_site_mutations_blocked(self):
        with patch.object(server.ws_bridge.HUB, 'request_browser') as request:
            code, _ = self.call('/api/wbot/command', {'action': 'click'}, Origin='https://example.invalid')
            self.assertEqual(code, 403)
            request.assert_not_called()

    def test_action_forwarding_retains_strict_target(self):
        target = {'browserId': 'a', 'tabId': 1, 'frameId': 2, 'documentId': 'doc'}
        with patch.object(server.ws_bridge.HUB, 'request_browser', return_value={'ok': True, 'result': True}) as request:
            status, result = self.call('/api/wbot/command', {
                'target': target, 'action': 'input', 'xpath': '//input',
                'options': {'value': '中文', 'strict': True, 'index': 0}})
            self.assertEqual(status, 200)
            self.assertTrue(result['result'])
            self.assertEqual(request.call_args.args, (target, 'input', '//input'))
            self.assertEqual(request.call_args.kwargs['options']['value'], '中文')
        for body in [{'action': 'eval', 'xpath': '//input'},
                     {'action': 'click', 'xpath': '//input', 'options': {'index': True}},
                     {'action': 'click', 'xpath': '//input', 'options': {'strict': 'false'}}]:
            self.assertEqual(self.call('/api/wbot/command', body)[0], 400)


if __name__ == '__main__':
    unittest.main()
