"""wbot 辅助模块回归；HTTP 仅访问测试自建的本机服务。"""
import importlib.util
import json as stdjson
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
import zipfile

from wbot import files, folders, strings, regex, json, csv, xzip, request, excel


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_binary_copy_move(self):
        source, copied, moved = (self.root / name for name in ("中文.txt", "copy.txt", "move.txt"))
        files.write_text(source, "第一行\n")
        files.append_text(source, "第二行")
        self.assertEqual(files.read_text(source), "第一行\n第二行")
        files.copy(source, copied)
        self.assertEqual(files.checksum(source), files.checksum(copied))
        files.move(copied, moved)
        self.assertFalse(copied.exists())
        self.assertEqual(files.size(moved), len(files.read_bytes(source)))
        self.assertEqual(len(files.list_files(self.root)), 2)
        files.delete(moved)
        self.assertFalse(files.exists(moved))

    def test_no_overwrite_is_default(self):
        target = self.root / "keep.txt"
        files.write_text(target, "keep")
        with self.assertRaises(FileExistsError):
            files.write_text(target, "lose")
        self.assertEqual(files.read_text(target), "keep")
        with self.assertRaises(ValueError):
            files.copy(target, target, overwrite=True)

    def test_path_bounds_and_directories(self):
        self.assertEqual(files.safe_path("child/file", root=self.root), self.root / "child/file")
        with self.assertRaises(ValueError):
            files.safe_path("../escape", root=self.root)
        with self.assertRaises(ValueError):
            files.list_files(self.root, "../*")
        source = self.root / "source"
        folders.create(source / "sub")
        files.write_text(source / "sub/a.txt", "a")
        with self.assertRaises(ValueError):
            folders.copy(source, source / "recursive")
        folders.copy(source, self.root / "copy")
        self.assertEqual(len(folders.list_folders(source, recursive=True)), 1)
        with self.assertRaises(OSError):
            folders.delete(source)
        folders.delete(source, recursive=True)
        self.assertFalse(source.exists())

    def test_json_csv_roundtrip(self):
        value = {"中文": [1, True, None], "nested": {"x": 2}}
        json.dump(value, self.root / "data.json")
        self.assertEqual(json.load(self.root / "data.json"), value)
        rows = [{"名称": "含,逗号", "说明": '有"引号\n换行'}, {"名称": "二", "说明": ""}]
        csv.write(self.root / "data.csv", rows)
        self.assertEqual(csv.read(self.root / "data.csv"), rows)
        with self.assertRaises(FileExistsError):
            csv.write(self.root / "data.csv", rows)
        csv.write(self.root / "raw.csv", [["a", "b"], ["1", "2"]], header=False)
        self.assertEqual(csv.read(self.root / "raw.csv", header=False), [["a", "b"], ["1", "2"]])

    def test_strings_and_regex(self):
        self.assertTrue(strings.contains("Straße", "STRASSE", ignore_case=True))
        self.assertEqual(strings.base64_decode(strings.base64_encode("你好")), "你好")
        self.assertEqual(strings.normalize("ＡＢ１２"), "AB12")
        self.assertEqual(strings.substring("abcdef", 2, 2), "cd")
        self.assertEqual(regex.findall(r"\d+", "a12b34"), ["12", "34"])
        self.assertEqual(regex.replace(r"\s+", " ", "a  b"), "a b")
        with self.assertRaises(ValueError):
            strings.substring("x", 0, -1)


class ZipTests(unittest.TestCase):
    setUp = FileTests.setUp
    tearDown = FileTests.tearDown

    def test_zip_roundtrip_empty_directory(self):
        source = self.root / "source"
        folders.create(source / "empty")
        files.write_text(source / "中文.txt", "归档内容")
        archive = self.root / "a.zip"
        xzip.zip(source, archive)
        extracted = xzip.unzip(archive, self.root / "out")
        self.assertEqual(len(extracted), 1)
        self.assertTrue((self.root / "out/source/empty").is_dir())
        self.assertEqual(files.read_text(self.root / "out/source/中文.txt"), "归档内容")
        with self.assertRaises(FileExistsError):
            xzip.unzip(archive, self.root / "out")
        with self.assertRaises(ValueError):
            xzip.unzip(archive, self.root / "small", max_bytes=1)
        self.assertFalse((self.root / "small").exists())

    def test_traversal_preflight_writes_nothing(self):
        for bad in ("../escape.txt", "C:/escape.txt", "/escape.txt", "dir/../../escape", "dir\\..\\escape", "a:stream", "NUL.txt"):
            with self.subTest(bad=bad):
                archive = self.root / "bad.zip"
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr("valid.txt", "must not extract")
                    z.writestr(bad, "bad")
                with self.assertRaises(ValueError):
                    xzip.unzip(archive, self.root / "badout")
                self.assertFalse((self.root / "badout").exists())

    def test_reject_symlink_and_file_parent_conflicts(self):
        archive = self.root / "link.zip"
        with zipfile.ZipFile(archive, "w") as z:
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(entry, "../outside")
        with self.assertRaises(ValueError):
            xzip.unzip(archive, self.root / "links")
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("a", "file")
            z.writestr("a/b", "child")
        with self.assertRaises(ValueError):
            xzip.unzip(archive, self.root / "conflicts")
        self.assertFalse((self.root / "conflicts").exists())

    def test_duplicate_names_and_encryption(self):
        archive = self.root / "dupe.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("A", "first")
            z.writestr("a", "second")
        with self.assertRaises(ValueError):
            xzip.unzip(archive, self.root / "duplicates")
        with self.assertRaises(NotImplementedError):
            xzip.zip(self.root, self.root / "encrypted.zip", password="secret")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def do_GET(self):
        status = 404 if self.path.startswith("/missing") else 200
        body = stdjson.dumps({"path": self.path, "text": "你好"}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        result = stdjson.dumps({"body": body.decode(), "type": self.headers.get("Content-Type"), "custom": self.headers.get("X-Test")}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=2)

    def test_get_and_error_response(self):
        response = request.get(self.base + "/test?old=1", params={"q": "中文"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("old=1&q=", response.json()["path"])
        self.assertIn("你好", response.text)
        error = request.get(self.base + "/missing")
        self.assertEqual(error.status, 404)
        self.assertFalse(error.ok)
        with self.assertRaises(HTTPError):
            error.raise_for_status()

    def test_json_form_headers(self):
        response = request.post(self.base, json={"中文": 7}, headers={"X-Test": "yes"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(stdjson.loads(response.json()["body"]), {"中文": 7})
        self.assertEqual(response.json()["custom"], "yes")
        self.assertEqual(request.post(self.base, body={"a": "b c"}).json()["body"], "a=b+c")
        self.assertEqual(request.post(self.base, json=None).json()["body"], "null")

    def test_limits_and_download(self):
        with self.assertRaises(ValueError):
            request.get("file:///not-http")
        with self.assertRaises(ValueError):
            request.get(self.base, max_bytes=3)
        with self.assertRaises(ValueError):
            request.post(self.base, body="x", json={})
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "download.json"
            response = request.download(self.base, target)
            self.assertEqual(target.read_bytes(), response.content)
            with self.assertRaises(FileExistsError):
                request.download(self.base, target)
            missing = Path(temporary) / "missing.json"
            with self.assertRaises(HTTPError):
                request.download(self.base + "/missing", missing)
            self.assertFalse(missing.exists())
        self.assertEqual(request.extract_filename("https://example.com/a%20b.csv?q=1"), "a b.csv")
        with self.assertRaises(ValueError):
            request.extract_filename("https://example.com/a%2fb")


@unittest.skipUnless(importlib.util.find_spec("openpyxl"), "可选 openpyxl 未安装")
class ExcelTests(unittest.TestCase):
    def test_roundtrip_cells_ranges_and_sheets(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "book.xlsx"
            with excel.create() as book:
                sheet = book.get_sheet_by_index(1)
                sheet.name = "数据"
                sheet.range("A1:B2").value = [["姓名", "值"], ["张三", 42]]
                self.assertEqual(sheet.append_row(["李四", 3]), 3)
                sheet.cell("C", 2).value = "=B2*2"
                self.assertEqual(sheet.cell("C", 2).value, "=B2*2")
                self.assertEqual(sheet.read("A2:B2"), [["张三", 42]])
                with self.assertRaises(ValueError):
                    sheet.range("A1:B2").value = [[1]]
                book.create_sheet("前页", "first")
                self.assertEqual(book.get_sheet_by_index(1).name, "前页")
                book.save_as(path)
                with self.assertRaises(FileExistsError):
                    book.save_as(path)
            with self.assertRaises(ValueError):
                sheet.read()
            with excel.open(path) as loaded:
                sheet = loaded.get_sheet_by_name("数据")
                self.assertEqual(sheet.cell("B", 2).value, 42)
                self.assertEqual(sheet.cell("C", 2).value, "=B2*2")
                sheet.range("A2:B2").clear()
                self.assertEqual(sheet.read("A2:B2"), [[None, None]])
                loaded.save()

    def test_explicit_backend_and_boundaries(self):
        with self.assertRaises(NotImplementedError):
            excel.create(kind="office")
        with excel.create() as book:
            with self.assertRaises(ValueError):
                book.get_sheet_by_index(0)
            with self.assertRaises(ValueError):
                book.get_active_sheet().range("A:A")
            with self.assertRaises(ValueError):
                book.delete_sheet(book.sheet_names[0])
            with self.assertRaises(ValueError):
                book.save()


if __name__ == "__main__":
    unittest.main()
