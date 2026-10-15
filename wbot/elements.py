"""XPath 元素库：独立的 SQLite 存储格式，不读取影刀私有资源。"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from lxml import etree


def validate_xpath(value: str) -> str:
    """验证 XPath 1.0 元素定位表达式；动作不能接收标量或属性节点。"""
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        raise ValueError('xpath 必须是 1–8192 字符的非空字符串')
    value = value.strip()
    try:
        compiled = etree.XPath(value)
        result = compiled(etree.XML(b'<root><div id="probe">text<span/></div></root>'))
    except etree.XPathError as exc:
        raise ValueError(f'XPath 无效或使用了不支持的变量/命名空间: {exc}') from exc
    if not isinstance(result, list) or any(not isinstance(x, etree._Element) or not isinstance(x.tag, str) for x in result):
        raise ValueError('元素 XPath 必须返回元素节点，不能返回字符串、数值、属性或文本节点')
    # 从谓词和字符串以外的选择路径检查空结果的属性 / 文本节点选择。
    path, depth, quote = [], 0, None
    for char in value:
        if quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
        elif depth == 0:
            path.append(char)
    selection = ''.join(path)
    if re.search(r'@|\b(?:attribute|namespace)\s*::|\b(?:text|comment|processing-instruction|node)\s*\(', selection):
        raise ValueError('元素 XPath 不能选择属性、命名空间或非元素节点；请用 * 选择元素')
    return value


def _text(value, field, limit, default=None):
    if value is None and default is not None:
        value = default
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ValueError(f'{field} 必须是不含 NUL、最多 {limit} 字符的字符串')
    return value


def _record(record):
    if not isinstance(record, dict):
        raise ValueError('record 必须是对象')
    name = _text(record.get('name'), 'name', 200).strip()
    group = _text(record.get('group'), 'group', 200, '默认').strip()
    if not name or not group:
        raise ValueError('名称和分组不能为空')
    record_id = _text(record.get('id'), 'id', 128, str(uuid4()))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', record_id):
        raise ValueError('id 只能包含字母、数字、下划线和连字符')
    frame = record.get('frame')
    if frame is not None and not isinstance(frame, dict):
        raise ValueError('frame 必须是对象或 null')
    try:
        frame_json = json.dumps(frame, ensure_ascii=False, allow_nan=False)
        if len(frame_json) > 16384:
            raise ValueError('frame 超过 16384 字符')
    except (TypeError, RecursionError, ValueError) as exc:
        raise ValueError(f'frame 必须是有效且大小受限的 JSON: {exc}') from exc
    now = datetime.now(timezone.utc).isoformat()
    created = record.get('created_at') or now
    updated = record.get('updated_at') or now
    for field, value in [('created_at', created), ('updated_at', updated)]:
        _text(value, field, 64)
        try:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError(f'{field} 必须是 ISO 日期时间') from exc
    return dict(id=record_id, name=name, group=group, xpath=validate_xpath(record.get('xpath')),
                description=_text(record.get('description'), 'description', 10000, ''),
                url=_text(record.get('url'), 'url', 8192, ''), frame=frame_json,
                created_at=created, updated_at=updated)


class ElementLibrary:
    """持久化元素库。每个调用单独连接；同名约束为 (group, name)。"""
    def __init__(self, path=None):
        if path is None:
            path = os.environ.get('WBOT_ELEMENT_LIBRARY') or None
        self.path = Path(path).expanduser() if path is not None else Path.home() / '.xpath_studio' / 'elements.sqlite3'
        if str(path) == ':memory:':
            raise ValueError('每次调用使用独立连接，请使用磁盘数据库路径')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS elements (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, "group" TEXT NOT NULL,
                xpath TEXT NOT NULL, description TEXT NOT NULL, url TEXT NOT NULL,
                frame TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE("group", name))''')

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _decode(row):
        result = dict(row)
        result['frame'] = json.loads(result['frame'])
        return result

    @staticmethod
    def _write(conn, item):
        conn.execute('''INSERT INTO elements (id,name,"group",xpath,description,url,frame,created_at,updated_at)
            VALUES (:id,:name,:group,:xpath,:description,:url,:frame,:created_at,:updated_at)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,"group"=excluded."group",xpath=excluded.xpath,
            description=excluded.description,url=excluded.url,frame=excluded.frame,updated_at=excluded.updated_at''', item)

    def upsert(self, record):
        item = _record(record)
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT * FROM elements WHERE id=?', (item['id'],)).fetchone()
            if old:
                item['created_at'] = old['created_at']
            item['updated_at'] = datetime.now(timezone.utc).isoformat()
            try:
                self._write(conn, item)
            except sqlite3.IntegrityError as exc:
                raise ValueError('该分组已存在同名元素，请编辑现有元素或修改名称') from exc
        return self._decode(item)

    def get(self, id):
        _text(id, 'id', 128)
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM elements WHERE id=?', (id,)).fetchone()
        if row is None:
            raise KeyError(f'元素不存在: {id}')
        return self._decode(row)

    def get_by_name(self, name, group='默认'):
        _text(name, 'name', 200)
        _text(group, 'group', 200)
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM elements WHERE name=? AND "group"=?', (name, group)).fetchone()
        if row is None:
            raise KeyError(f'元素不存在: {group}/{name}')
        return self._decode(row)

    def list(self, query='', group=''):
        _text(query, 'query', 8192)
        _text(group, 'group', 200)
        escaped = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        with self._connect() as conn:
            rows = conn.execute('''SELECT * FROM elements WHERE (?='' OR "group"=?) AND
                (name LIKE ? ESCAPE '\\' OR xpath LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')
                ORDER BY "group",name,id''', (group, group, escaped, escaped, escaped)).fetchall()
        return [self._decode(row) for row in rows]

    def delete(self, id):
        _text(id, 'id', 128)
        with self._connect() as conn:
            return conn.execute('DELETE FROM elements WHERE id=?', (id,)).rowcount > 0

    def export_data(self):
        return {'format': 'wbot-elements', 'version': 1, 'items': self.list()}

    def import_data(self, data, conflict='error'):
        if conflict not in ('error', 'replace', 'skip'):
            raise ValueError('conflict 必须是 error、replace 或 skip')
        if not isinstance(data, dict) or data.get('format') != 'wbot-elements' or type(data.get('version')) is not int or data['version'] != 1:
            raise ValueError('需要 format=wbot-elements、version=1 的元素库 JSON')
        if not isinstance(data.get('items'), list) or len(data['items']) > 10000:
            raise ValueError('items 必须是最多 10000 条记录的数组')
        items = [_record(item) for item in data['items']]
        counts = {'inserted': 0, 'replaced': 0, 'skipped': 0, 'total': len(items)}
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for item in items:
                matches = conn.execute('SELECT * FROM elements WHERE id=? OR ("group"=? AND name=?)',
                                       (item['id'], item['group'], item['name'])).fetchall()
                if matches:
                    if conflict == 'skip':
                        counts['skipped'] += 1
                        continue
                    if conflict == 'error' or len(matches) > 1:
                        raise ValueError(f'导入冲突: {item["group"]}/{item["name"]}；整个导入已回滚')
                    item['id'] = matches[0]['id']
                    item['created_at'] = matches[0]['created_at']
                    counts['replaced'] += 1
                else:
                    counts['inserted'] += 1
                self._write(conn, item)
        return counts
