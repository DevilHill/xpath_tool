"""企业策略安装的测试。

**刻意用假 winreg**：本机 `reg.exe` 被安全策略封禁（连只读的 `reg query` 都被拦），
而且写浏览器策略是有副作用的操作。所以这里把 ``policy_install.winreg`` 换成内存实现，
既能完整覆盖读/写/幂等/卸载逻辑，又**完全不碰真实注册表**。

同时把 ``policy_root()`` 指向临时目录，避免污染真实的 ``%LOCALAPPDATA%``。

用法：python tools/test_policy_install.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import zipfile
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import crx, policy_install as pi  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not ok else ""))


# --------------------------------------------------------------------------- #
# 假 winreg（内存）
# --------------------------------------------------------------------------- #
class FakeKey:
    """模拟 winreg 的 HKEY 对象。

    注意真实对象支持 `with` 协议（policy_install 里就是这么用的），
    所以这里必须实现 __enter__/__exit__，否则会被 except 吃掉变成「读策略失败」。
    """

    def __init__(self, store: dict, path: str, access: int = 1):
        self.store = store
        self.path = path
        self.access = access

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 0x0002
    KEY_QUERY_VALUE = 0x0001
    REG_SZ = 1

    def __init__(self):
        self.store: dict[str, list[tuple[str, str]]] = {}
        self.calls: list[str] = []

    # --- API ---
    def CreateKeyEx(self, hive, path, reserved=0, access=0):
        self.calls.append(f"CreateKeyEx({path})")
        self.store.setdefault(path, [])
        return FakeKey(self.store, path, access)

    def OpenKey(self, hive, path):
        self.calls.append(f"OpenKey({path})")
        if path not in self.store:
            raise FileNotFoundError(path)
        return FakeKey(self.store, path)

    def EnumValue(self, key, index):
        if not key.access & self.KEY_QUERY_VALUE:
            exc = PermissionError("query access denied")
            exc.winerror = 5
            raise exc
        items = self.store.get(key.path, [])
        if index >= len(items):
            exc = OSError("no more values")
            exc.winerror = 259
            raise exc
        name, val = items[index]
        return name, val, self.REG_SZ

    def SetValueEx(self, key, name, reserved, type_, value):
        self.calls.append(f"SetValueEx({key.path},{name}={value})")
        items = self.store.setdefault(key.path, [])
        for i, (n, _) in enumerate(items):
            if n == name:
                items[i] = (name, value)
                return
        items.append((name, value))

    def DeleteValue(self, key, name):
        self.calls.append(f"DeleteValue({key.path},{name})")
        items = self.store.setdefault(key.path, [])
        self.store[key.path] = [(n, v) for n, v in items if n != name]

    def DeleteKey(self, hive, path):
        self.calls.append(f"DeleteKey({path})")
        if path not in self.store:
            raise FileNotFoundError(path)
        del self.store[path]

    def CloseKey(self, key):
        pass

    # --- 断言辅助 ---
    def entries(self, browser_key: str) -> list[str]:
        path = pi._policy_path(browser_key)
        return [v for _, v in self.store.get(path or "", [])]


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="xps-policy-", dir=os.path.join(ROOT, "build"))
    # 把产物目录重定向到临时目录
    pi.policy_root = lambda: __import__("pathlib").Path(tmp)

    fake = FakeWinreg()
    pi.winreg = fake
    check("状态查询不会生成密钥", not pi.status("chrome").get("policyConfigured") and not pi.key_file().exists())

    print("=" * 72)
    print("[1] 密钥与扩展 ID")
    print("=" * 72)
    key, created = pi.ensure_key()
    check("首次调用生成密钥", created is True)
    check("密钥文件已落盘", pi.key_file().is_file())
    eid = pi.extension_id()
    check("扩展 ID 32 位且在 a-p 内",
          len(eid) == 32 and all(c in "abcdefghijklmnop" for c in eid), eid)
    key2, created2 = pi.ensure_key()
    check("再次调用复用密钥（ID 不变）",
          created2 is False and crx.extension_id(key2["n"], key2["e"]) == eid)

    print()
    print("=" * 72)
    print("[2] 扩展副本：注入 key + 改写端口")
    print("=" * 72)
    dest = pi.materialize_extension(EXT, 8799, key)
    check("副本目录已生成", dest.is_dir())
    mf = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    check("manifest 注入了 key", "key" in mf)
    check("key 与签名密钥一致（base64 SPKI）",
          mf.get("key") == crx.manifest_key(key["n"], key["e"]))
    bg = (dest / "background.js").read_text(encoding="utf-8")
    check("bridge 端口已改写为 8799", "http://127.0.0.1:8799" in bg)
    check("源码目录未被污染（无 key）",
          "key" not in json.loads((__import__("pathlib").Path(EXT) / "manifest.json")
                                  .read_text(encoding="utf-8")))

    print()
    print("=" * 72)
    print("[3] CRX 打包与签名")
    print("=" * 72)
    blob, cid, version = pi.build_crx(EXT, 8799)
    check("CRX 魔数为 Cr24", blob[:4] == b"Cr24")
    check("返回的扩展 ID 与密钥一致", cid == eid)
    parsed = crx.parse_crx3(blob)
    check("CRX 内签名可验签",
          crx.verify_signature(key["n"], key["e"],
                               crx.signed_payload(parsed["signed_header_data"], parsed["zip"]),
                               parsed["signature"]))
    check("CRX 里的 public_key 与 manifest key 是同一把",
          parsed["public_key"] == __import__("base64").b64decode(mf["key"]))
    check("CRX 内的 crx_id 与扩展 ID 对应",
          crx.encode_app_id(crx.pb_fields(parsed["signed_header_data"])[0][1]) == eid)
    check("CRX 尾部是合法 zip 且含 manifest.json",
          "manifest.json" in zipfile.ZipFile(io.BytesIO(parsed["zip"])).namelist())
    check("版本号来自 manifest", version == mf.get("version"), version)

    print()
    print("=" * 72)
    print("[4] update.xml")
    print("=" * 72)
    xml = pi.update_xml(8799)
    check("appid 正确", f"appid='{eid}'" in xml)
    check("codebase 指向本机服务",
          "codebase='http://127.0.0.1:8799/extension/extension.crx'" in xml)
    check("version 正确", f"version='{version}'" in xml)

    print()
    print("=" * 72)
    print("[5] 注册表读写")
    print("=" * 72)
    check("chrome 策略路径正确",
          pi._policy_path("chrome") == r"Software\Policies\Google\Chrome\ExtensionInstallForcelist")
    check("edge 策略路径正确",
          pi._policy_path("edge") == r"Software\Policies\Microsoft\Edge\ExtensionInstallForcelist")
    check("brave 策略路径正确",
          pi._policy_path("brave")
          == r"Software\Policies\BraveSoftware\Brave\ExtensionInstallForcelist")
    check("未知浏览器返回 None", pi._policy_path("nope") is None)
    check("无策略时读到空列表", pi.read_forcelist("chrome") == [])

    # 预置一条用户自己的策略，验证不会被我们覆盖
    other = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa;https://example.com/update.xml"
    fake.store[pi._policy_path("chrome")] = [("1", other)]

    print()
    print("=" * 72)
    print("[6] 安装策略")
    print("=" * 72)
    res = pi.install_policy("chrome", EXT, 8799)
    check("install_policy 成功", res.get("ok") is True, str(res))
    check("返回扩展 ID", res.get("extId") == eid)
    entries = fake.entries("chrome")
    check("策略里新增了本扩展", any(v.split(";")[0] == eid for v in entries), str(entries))
    check("原有策略被保留", other in entries, str(entries))
    check("update_url 指向本机服务",
          any(v.split(";")[0] == eid and v.split(";")[1].startswith("http://127.0.0.1:8799/")
              for v in entries), str(entries))
    check("条目从 1 开始编号", fake.store[pi._policy_path("chrome")][0][0] == "1")

    print()
    print("=" * 72)
    print("[7] 幂等：重复安装不应产生重复条目")
    print("=" * 72)
    pi.install_policy("chrome", EXT, 8799)
    entries2 = fake.entries("chrome")
    mine = [v for v in entries2 if v.split(";")[0] == eid]
    check("本扩展只有一条", len(mine) == 1, str(mine))
    check("总数仍为 2", len(entries2) == 2, str(entries2))
    # 换端口后应替换而不是新增
    pi.install_policy("chrome", EXT, 8800)
    entries3 = fake.entries("chrome")
    mine3 = [v for v in entries3 if v.split(";")[0] == eid]
    check("换端口后仍是 1 条且指向新端口",
          len(mine3) == 1 and ":8800/" in mine3[0], str(mine3))

    print()
    print("=" * 72)
    print("[8] 状态查询")
    print("=" * 72)
    st = pi.status("chrome")
    check("status 报告已安装", st.get("installed") is True, str(st))
    check("status 返回扩展 ID", st.get("extId") == eid)
    check("status 带策略路径", "HKCU\\" in str(st.get("policyPath")), str(st.get("policyPath")))
    st2 = pi.status("edge")
    check("edge 未装时 installed 为 False", st2.get("installed") is False, str(st2))

    print()
    print("=" * 72)
    print("[9] 卸载策略（只删自己的）")
    print("=" * 72)
    rm = pi.remove_policy("chrome")
    check("卸载成功", rm.get("ok") is True, str(rm))
    check("删除了 1 条", rm.get("removed") == 1, str(rm))
    left = fake.entries("chrome")
    check("用户原有策略仍在", left == [other], str(left))
    st3 = pi.status("chrome")
    check("卸载后 installed 为 False", st3.get("installed") is False)
    rm2 = pi.remove_policy("chrome")
    check("重复卸载不报错且 removed=0", rm2.get("ok") is True and rm2.get("removed") == 0, str(rm2))

    print()
    print("=" * 72)
    print("[10] 边界情况")
    print("=" * 72)
    bad = pi.install_policy("nope", EXT, 8799)
    check("未知浏览器报错", bad.get("ok") is False, str(bad))
    saved = pi.winreg
    pi.winreg = None
    nonwin = pi.install_policy("chrome", EXT, 8799)
    check("无 winreg 时明确报错", nonwin.get("ok") is False and "Windows" in nonwin.get("error", ""),
          str(nonwin))
    check("无 winreg 时 status 标记不支持", pi.status("chrome").get("supported") is False)
    check("无 winreg 时卸载明确报错", pi.remove_policy("chrome").get("ok") is False)
    pi.winreg = saved

    # 读注册表异常时不应覆盖已有策略
    class Boom(FakeWinreg):
        def OpenKey(self, hive, path):
            raise PermissionError("blocked")

    pi.winreg = Boom()
    pi.winreg.store[pi._policy_path("chrome")] = [("1", other)]
    blocked = pi.install_policy("chrome", EXT, 8799)
    check("读注册表被拒时中止（不误删已有策略）",
          blocked.get("ok") is False and "读取现有策略失败" in blocked.get("error", ""), str(blocked))
    pi.winreg = saved

    print()
    print("=" * 72)
    print("[11] 警告与步骤文案")
    print("=" * 72)
    pi.install_policy("chrome", EXT, 8799)
    res2 = pi.install_policy("chrome", EXT, 8799)
    check("包含副作用警告（由贵单位管理）",
          any("由贵单位管理" in w for w in res2.get("warnings", [])), str(res2.get("warnings")))
    check("包含「退出并重开浏览器」步骤",
          any("重新打开浏览器" in s for s in res2.get("steps", [])), str(res2.get("steps")))
    check("包含卸载提示", any("卸载策略" in s for s in res2.get("steps", [])), str(res2.get("steps")))

    check("策略存在不等于安装已验证", pi.status("chrome").get("policyConfigured") is True and
          pi.status("chrome").get("installationVerified") is False)

    class WriteDenied(FakeWinreg):
        def CreateKeyEx(self, *args):
            exc = PermissionError("write blocked")
            exc.winerror = 5
            raise exc

    pi.winreg = WriteDenied()
    denied = pi.install_policy("chrome", EXT, 8799)
    check("写入拒绝保留错误码与阶段", denied.get("diagnostics", {}).get("winerror") == 5 and
          denied.get("stage") == "policy-write", str(denied))
    check("策略写入失败提供引导安装", denied.get("fallback") == "guided")

    class EnumDenied(FakeWinreg):
        def EnumValue(self, key, index):
            exc = PermissionError("enumeration blocked")
            exc.winerror = 5
            raise exc

    pi.winreg = EnumDenied()
    pi.winreg.store[pi._policy_path("chrome")] = [("1", other)]
    detail = {}
    check("枚举拒绝不冒充空策略", pi.read_forcelist("chrome", detail) is None and detail.get("winerror") == 5)
    check("枚举失败不继续写值", not pi.write_forcelist("chrome", ["x"], {}) and
          not any("SetValueEx" in c for c in pi.winreg.calls))
    pi.winreg = saved
    check("收缩列表清理高位条目", pi.write_forcelist("chrome", [other]) and fake.entries("chrome") == [other])

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 72)
    print(f"结果：通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
    print("全部通过 ✅" if not FAIL else "存在失败 ❌")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
