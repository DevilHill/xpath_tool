import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest

from wbot.elements import ElementLibrary, validate_xpath
from wbot.selector import Selector, SelectorStore


class ElementLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'nested' / 'elements.sqlite3'
        self.library = ElementLibrary(self.path)

    def record(self, name='登录', **extra):
        return dict(name=name, xpath="//button[@id='login']", **extra)

    def export(self, *records):
        return dict(format='wbot-elements', version=1, items=list(records))

    def test_reopen_update_delete(self):
        original = self.library.upsert(self.record(frame={'frameId': 3, 'url': 'https://example.test/frame'}))
        reopened = ElementLibrary(self.path)
        self.assertEqual(reopened.get(original['id']), original)
        original['description'] = 'updated'
        result = reopened.upsert(original)
        self.assertEqual(result['created_at'], original['created_at'])
        self.assertEqual(reopened.get_by_name('登录')['description'], 'updated')
        self.assertTrue(reopened.delete(original['id']))
        self.assertFalse(reopened.delete(original['id']))
        with self.assertRaises(KeyError):
            reopened.get(original['id'])

    def test_unique_group_and_parameterized_query(self):
        self.library.upsert(self.record())
        with self.assertRaises(ValueError):
            self.library.upsert(self.record())
        self.library.upsert(self.record(group='其他'))
        self.library.upsert(self.record("%' OR 1=1 --", group='特殊'))
        self.assertEqual(len(self.library.list()), 3)
        self.assertEqual(len(self.library.list("%' OR 1=1 --")), 1)
        self.assertEqual(len(self.library.list('', '其他')), 1)
        self.assertEqual(len(self.library.list('_')), 0)

    def test_import_error_rolls_back_prior_inserts(self):
        self.library.upsert(self.record())
        before = self.library.export_data()
        with self.assertRaises(ValueError):
            self.library.import_data(self.export(self.record('新增'), self.record()))
        self.assertEqual(self.library.export_data(), before)

    def test_import_invalid_record_rolls_back(self):
        with self.assertRaises(ValueError):
            self.library.import_data(self.export(self.record('新增'), {'name': '非法', 'xpath': 'count(//div)'}))
        self.assertEqual(self.library.list(), [])

    def test_import_skip_replace_and_roundtrip(self):
        saved = self.library.upsert(self.record(description='before'))
        data = self.export(self.record(description='after'), self.record('新元素'))
        counts = self.library.import_data(data, conflict='skip')
        self.assertEqual(counts, dict(inserted=1, replaced=0, skipped=1, total=2))
        counts = self.library.import_data(data, conflict='replace')
        self.assertEqual(counts['replaced'], 2)
        changed = self.library.get_by_name('登录')
        self.assertEqual(changed['id'], saved['id'])
        self.assertEqual(changed['created_at'], saved['created_at'])
        self.assertEqual(changed['description'], 'after')
        other = ElementLibrary(Path(self.tmp.name) / 'copy.sqlite3')
        other.import_data(json.loads(json.dumps(self.library.export_data())))
        self.assertEqual(other.export_data(), self.library.export_data())

    def test_import_ambiguous_identity_conflict(self):
        first = self.library.upsert(self.record('one'))
        self.library.upsert(self.record('two'))
        before = self.library.export_data()
        with self.assertRaises(ValueError):
            self.library.import_data(self.export(dict(first, name='two')), conflict='replace')
        self.assertEqual(before, self.library.export_data())

    def test_validation_and_element_only_xpath(self):
        for xpath in ('', None, '//div[', 'count(//div)', 'true()', 'string(//div)', '//missing/@title',
                      '//missing/text()', '//missing/comment()', '//missing/node()', '//missing/namespace::*', '$value'):
            with self.subTest(xpath=xpath), self.assertRaises(ValueError):
                validate_xpath(xpath)
        for xpath in ("//button[@title='a@b']", '//div[count(span)>0]', '(//div)[1]', '//a | //button', '//div/text()/..'):
            if xpath.endswith('text()/..'):
                # 保守限制中间非元素路径，文档约定以元素路径定位。
                continue
            self.assertEqual(validate_xpath(xpath), xpath)
        for extra in ({'name': ' '}, {'group': ''}, {'frame': []}, {'frame': {'bad': float('nan')}},
                      {'id': 'bad/id'}, {'created_at': 'yesterday'}, {'description': 9}):
            record = self.record()
            record.update(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.library.upsert(record)
        with self.assertRaises(ValueError):
            self.library.import_data(self.export(), 'merge')

    def test_concurrent_connections(self):
        def save(number):
            return self.library.upsert(self.record(str(number)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(save, range(40)))
        self.assertEqual(len(results), 40)
        self.assertEqual(len(ElementLibrary(self.path).list()), 40)

    def test_selector_store(self):
        saved = self.library.upsert(self.record(group='登录页', frame={'frameId': 0}))
        store = SelectorStore(self.path)
        selector = store('登录', group='登录页')
        self.assertEqual(selector.xpath(), saved['xpath'])
        self.assertEqual(str(selector), saved['xpath'])
        self.assertEqual(selector.name, '登录')
        self.assertEqual(selector.group, '登录页')
        self.assertEqual(selector.to_dict(), saved)
        selector.frame['frameId'] = 99
        self.assertEqual(selector.frame['frameId'], 0)
        self.assertEqual(Selector('//a', {'name': 'link'}).name, 'link')


if __name__ == '__main__':
    unittest.main()
