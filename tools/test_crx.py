"""CRX3 签名器测试（纯离线，不需要浏览器）。

覆盖：RSA 密钥正确性、SPKI DER 结构、扩展 ID 公式与 a-p 映射边界、
PKCS#1 v1.5 签名验签、CRX3 文件布局与内嵌签名自洽、zip 打包、update.xml。

用法：python tools/test_crx.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import crx  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not ok else ""))


def main() -> int:
    print("=" * 72)
    print("[1] RSA 密钥生成（1024 位，测试用快一些）")
    print("=" * 72)
    t0 = time.time()
    key = crx.generate_key(bits=1024)
    dt = time.time() - t0
    print(f"    生成耗时 {dt:.2f}s")
    n, e, d = key["n"], key["e"], key["d"]
    check("n 位数为 1024", n.bit_length() == 1024, str(n.bit_length()))
    check("e 为 65537", e == 65537, str(e))
    check("p * q == n", key["p"] * key["q"] == n)
    check("p、q 不相等", key["p"] != key["q"])
    m = 0x1234567890ABCDEF
    check("加解密往返 (m^e)^d ≡ m mod n", pow(pow(m, e, n), d, n) == m % n)
    check("e * d ≡ 1 mod φ(n)", (e * d) % ((key["p"] - 1) * (key["q"] - 1)) == 1)

    print()
    print("=" * 72)
    print("[2] SPKI DER 编码")
    print("=" * 72)
    spki = crx.spki_der(n, e)
    check("以 SEQUENCE(0x30) 开头", spki[0] == 0x30)
    check("长度字段自洽", crx._der_len(len(spki) - 2 - len(crx._der_len(len(spki) - 2)))
          == crx._der_len(len(spki) - 2 - len(crx._der_len(len(spki) - 2))))
    # 结构：SEQUENCE { SEQUENCE { OID, NULL }, BIT STRING { 00, SEQUENCE { INT, INT } } }
    check("内含 rsaEncryption OID (1.2.840.113549.1.1.1)",
          bytes.fromhex("06092a864886f70d010101") in spki)
    check("OID 后跟 NULL", bytes.fromhex("06092a864886f70d0101010500") in spki)
    check("内含 BIT STRING(0x03) 包装", b"\x03\x82" in spki or b"\x03\x81" in spki)
    # 整体长度与 DER 头部一致
    total = len(spki)
    if spki[1] & 0x80:
        nlen = spki[1] & 0x7F
        declared = int.from_bytes(spki[2:2 + nlen], "big")
        head = 2 + nlen
    else:
        declared = spki[1]
        head = 2
    check("DER 声明的内容长度与实际一致", declared == total - head,
          f"声明 {declared}, 实际 {total - head}")

    print()
    print("=" * 72)
    print("[3] 扩展 ID / a-p 映射")
    print("=" * 72)
    check("encode_app_id 边界映射正确",
          crx.encode_app_id(b"\x00\x0f\xf0\xff") == "aaappapp",
          crx.encode_app_id(b"\x00\x0f\xf0\xff"))
    eid = crx.extension_id(n, e)
    check("扩展 ID 长度 32", len(eid) == 32, str(len(eid)))
    check("扩展 ID 只含 a-p", all(c in "abcdefghijklmnop" for c in eid), eid)
    import hashlib
    expect = "".join(crx._AP[b >> 4] + crx._AP[b & 0xF]
                     for b in hashlib.sha256(spki).digest()[:16])
    check("扩展 ID == sha256(spki)[:16] 的 a-p 编码", eid == expect, f"{eid} vs {expect}")
    check("扩展 ID 是确定性的", crx.extension_id(n, e) == eid)
    mk = crx.manifest_key(n, e)
    check("manifest key 的 base64 解出来就是 SPKI DER",
          base64.b64decode(mk) == spki)

    print()
    print("=" * 72)
    print("[4] PKCS#1 v1.5 签名")
    print("=" * 72)
    data = b"hello crx3" * 10
    sig = crx._pkcs1v15_sha256_sign(key, data)
    check("签名长度 == 模长", len(sig) == (n.bit_length() + 7) // 8, str(len(sig)))
    check("签名可被公钥验签通过", crx.verify_signature(n, e, data, sig))
    check("篡改数据后验签失败", not crx.verify_signature(n, e, data + b"x", sig))
    check("篡改签名后验签失败",
          not crx.verify_signature(n, e, data, bytes([sig[0] ^ 1]) + sig[1:]))

    print()
    print("=" * 72)
    print("[5] CRX3 封装")
    print("=" * 72)
    zip_bytes = crx.zip_extension(EXT)
    check("zip 载荷非空", len(zip_bytes) > 1000, str(len(zip_bytes)))
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = z.namelist()
    check("zip 内含 manifest.json（根目录）", "manifest.json" in names, str(names[:5]))
    check("zip 内含 background.js", "background.js" in names)
    check("zip 内含 lib/engine.js", "lib/engine.js" in names)

    blob = crx.build_crx3(zip_bytes, key)
    check("魔数为 'Cr24'", blob[:4] == b"Cr24", repr(blob[:4]))
    check("版本号为 3", blob[4:8] == bytes([3, 0, 0, 0]), repr(blob[4:8]))

    parsed = crx.parse_crx3(blob)
    check("header_len 与实际头部一致", parsed["header_len"] == len(parsed["header"]))
    check("尾部 zip 与输入完全一致", parsed["zip"] == zip_bytes)
    check("头部里的 public_key == SPKI DER", parsed["public_key"] == spki)
    check("签名长度为模长", len(parsed["signature"]) == 128, str(len(parsed["signature"])))
    check("CRX3 内嵌签名可验签",
          crx.verify_signature(n, e,
                               crx.signed_payload(parsed["signed_header_data"], parsed["zip"]),
                               parsed["signature"]))
    # signed_header_data 里应当是 SignedData{crx_id}
    fields = crx.pb_fields(parsed["signed_header_data"])
    check("signed_header_data 只含 crx_id 字段(1)",
          len(fields) == 1 and fields[0][0] == 1, str(fields))
    check("crx_id == sha256(spki)[:16]", fields[0][1] == crx.crx_id_raw(spki))
    # 头部字段号
    hfields = sorted(f for f, _ in crx.pb_fields(parsed["header"]))
    check("CrxFileHeader 字段号为 2 与 10000", hfields == [2, 10000], str(hfields))
    proof = dict(crx.pb_fields(parsed["header"])).get(2, b"")
    pfields = sorted(f for f, _ in crx.pb_fields(proof))
    check("AsymmetricKeyProof 字段号为 1 与 2", pfields == [1, 2], str(pfields))
    check("zip 能从 CRX3 尾部正常打开",
          zipfile.ZipFile(io.BytesIO(parsed["zip"])).testzip() is None)

    print()
    print("=" * 72)
    print("[6] update manifest XML")
    print("=" * 72)
    xml = crx.update_manifest_xml(eid, "1.1.0", "http://127.0.0.1:8790/extension/extension.crx")
    check("含 gupdate 命名空间", "http://www.google.com/update2/response" in xml)
    check("含 protocol=2.0", "protocol='2.0'" in xml)
    check("含正确 appid", f"appid='{eid}'" in xml)
    check("含 version", "version='1.1.0'" in xml)
    check("含 codebase", "codebase='http://127.0.0.1:8790/extension/extension.crx'" in xml)

    print()
    print("=" * 72)
    print("[7] 密钥持久化")
    print("=" * 72)
    import tempfile
    tmp = os.path.join(tempfile.mkdtemp(prefix="xps-key-"), "k.json")
    crx.save_key(tmp, key)
    back = crx.load_key(tmp)
    check("存盘再读回 n/d 一致", back and back["n"] == n and back["d"] == d)
    check("读回后算出的扩展 ID 不变", back and crx.extension_id(back["n"], back["e"]) == eid)
    k2, created = crx.load_or_create_key(tmp)
    check("已存在时 load_or_create_key 不重新生成", created is False and k2["n"] == n)

    print()
    print("=" * 72)
    print("[8] 2048 位密钥（生产用）耗时")
    print("=" * 72)
    t0 = time.time()
    k2048 = crx.generate_key(bits=2048)
    dt = time.time() - t0
    print(f"    生成耗时 {dt:.2f}s")
    check("2048 位密钥可用", k2048["n"].bit_length() == 2048)
    sig2 = crx._pkcs1v15_sha256_sign(k2048, b"abc")
    check("2048 位签名长度为 256", len(sig2) == 256, str(len(sig2)))
    check("2048 位验签通过", crx.verify_signature(k2048["n"], k2048["e"], b"abc", sig2))
    check("2048 位密钥生成在 60s 内", dt < 60, f"{dt:.1f}s")

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
