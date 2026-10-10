"""CRX3 打包与签名 —— **纯标准库**实现。

为什么不用 `cryptography` / `pycryptodome`：本项目要求 exe 体积小、依赖少
（后端只用 `http.server` 也是同一个理由）。而这里需要的密码学只有
RSA PKCS#1 v1.5 + SHA256，Python 的原生大整数运算完全够用，不必拖进 OpenSSL。

文件格式（对照 Chromium `components/crx_file/crx3.proto` 与 `crx_creator.cc`）::

    "Cr24"                4 字节魔数
    [3, 0, 0, 0]          4 字节小端版本号
    uint32 LE             4 字节 = 紧随其后的 protobuf 头长度
    CrxFileHeader         protobuf
    ZIP 数据

protobuf 字段号（手写编码，不引 protobuf 库）::

    CrxFileHeader.sha256_with_rsa    = 2      (repeated AsymmetricKeyProof)
    CrxFileHeader.signed_header_data = 10000  (bytes)
    AsymmetricKeyProof.public_key    = 1
    AsymmetricKeyProof.signature     = 2
    SignedData.crx_id                = 1

签名覆盖的数据::

    b"CRX3 SignedData\\x00" + uint32 LE(len(signed_header_data))
    + signed_header_data + zip 数据

扩展 ID = ``sha256(SPKI DER)[:16]``，再把每个字节拆成两个 nibble，
按 ``0-9a-f -> a-p`` 映射成字符串。**manifest 里的 `key` 字段**就是 SPKI DER 的 base64，
这样未打包（guided）与 CRX（policy）两条路会得到**同一个扩展 ID**。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import secrets
import zipfile
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# RSA 密钥（纯 Python）
# --------------------------------------------------------------------------- #
_SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                 53, 59, 61, 67, 71, 73, 79, 83, 89, 97)


def _is_probable_prime(n: int, rounds: int = 24) -> bool:
    """Miller-Rabin 素性测试。"""
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    while True:
        cand = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        # 先用小素数筛一遍，能省掉绝大多数 Miller-Rabin
        if any(cand % p == 0 for p in _SMALL_PRIMES):
            continue
        if _is_probable_prime(cand):
            return cand


def generate_key(bits: int = 2048, e: int = 65537) -> dict[str, int]:
    """生成 RSA 密钥。2048 位纯 Python 大约几秒，属于一次性开销。"""
    half = bits // 2
    while True:
        p = _gen_prime(half)
        q = _gen_prime(bits - half)
        if p == q:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        phi = (p - 1) * (q - 1)
        if math.gcd(e, phi) != 1:
            continue
        d = pow(e, -1, phi)
        return {"n": n, "e": e, "d": d, "p": p, "q": q, "bits": bits}


def save_key(path: str | Path, key: dict[str, int]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: (v if k == "bits" else format(v, "x")) for k, v in key.items()}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_key(path: str | Path) -> dict[str, int] | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    try:
        return {k: (v if k == "bits" else int(v, 16)) for k, v in data.items()}
    except Exception:  # noqa: BLE001
        return None


def load_or_create_key(path: str | Path) -> tuple[dict[str, int], bool]:
    """返回 (key, 是否新建)。"""
    key = load_key(path)
    if key:
        return key, False
    key = generate_key()
    save_key(path, key)
    return key, True


# --------------------------------------------------------------------------- #
# DER / SPKI 编码
# --------------------------------------------------------------------------- #
def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _der_tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(content)) + content


def _der_int(n: int) -> bytes:
    b = n.to_bytes(max(1, (n.bit_length() + 7) // 8), "big")
    if b[0] & 0x80:  # 正数最高位为 1 时要补一个 0x00
        b = b"\x00" + b
    return _der_tlv(0x02, b)


_RSA_OID = bytes.fromhex("06092a864886f70d010101")  # 1.2.840.113549.1.1.1
_DER_NULL = b"\x05\x00"


def spki_der(n: int, e: int) -> bytes:
    """X.509 SubjectPublicKeyInfo。Chrome 的 manifest ``key`` 字段就是它的 base64。"""
    rsa_pub = _der_tlv(0x30, _der_int(n) + _der_int(e))
    alg = _der_tlv(0x30, _RSA_OID + _DER_NULL)
    return _der_tlv(0x30, alg + _der_tlv(0x03, b"\x00" + rsa_pub))


# --------------------------------------------------------------------------- #
# 扩展 ID
# --------------------------------------------------------------------------- #
_AP = "abcdefghijklmnop"


def crx_id_raw(spki: bytes) -> bytes:
    """CRX ID = sha256(SPKI DER) 的前 16 字节。"""
    return hashlib.sha256(spki).digest()[:16]


def encode_app_id(raw: bytes) -> str:
    """每个字节拆两个 nibble，按 0-9a-f -> a-p 映射。"""
    out: list[str] = []
    for b in raw:
        out.append(_AP[b >> 4])
        out.append(_AP[b & 0x0F])
    return "".join(out)


def extension_id(n: int, e: int) -> str:
    return encode_app_id(crx_id_raw(spki_der(n, e)))


def manifest_key(n: int, e: int) -> str:
    """写进 manifest.json 的 `key` 字段（base64 的 SPKI DER）。"""
    return base64.b64encode(spki_der(n, e)).decode("ascii")


# --------------------------------------------------------------------------- #
# 签名（PKCS#1 v1.5 + SHA256）
# --------------------------------------------------------------------------- #
_SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _pkcs1v15_sha256_sign(key: dict[str, int], data: bytes) -> bytes:
    n, d = key["n"], key["d"]
    k = (n.bit_length() + 7) // 8
    t = _SHA256_DIGESTINFO + hashlib.sha256(data).digest()
    if k < len(t) + 11:
        raise ValueError("RSA 密钥太短，无法容纳 PKCS#1 v1.5 填充")
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    m = int.from_bytes(em, "big")
    return pow(m, d, n).to_bytes(k, "big")


def verify_signature(n: int, e: int, data: bytes, sig: bytes) -> bool:
    """用公钥验签。生产代码用不到，供测试自检。"""
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    t = _SHA256_DIGESTINFO + hashlib.sha256(data).digest()
    return em == b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


# --------------------------------------------------------------------------- #
# protobuf 手写编码 / 解析
# --------------------------------------------------------------------------- #
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _pb_bytes(field: int, data: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = 0
    val = 0
    while True:
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, i
        shift += 7


def pb_fields(buf: bytes) -> list[tuple[int, Any]]:
    """极简 protobuf 字段遍历，仅支持 length-delimited 与 varint。测试用。"""
    out: list[tuple[int, Any]] = []
    i = 0
    while i < len(buf):
        tag, i = _read_varint(buf, i)
        field, wire = tag >> 3, tag & 7
        if wire == 2:
            ln, i = _read_varint(buf, i)
            out.append((field, buf[i:i + ln]))
            i += ln
        elif wire == 0:
            val, i = _read_varint(buf, i)
            out.append((field, val))
        else:
            raise ValueError(f"不支持的 protobuf wire type: {wire}")
    return out


# --------------------------------------------------------------------------- #
# CRX3
# --------------------------------------------------------------------------- #
_MAGIC = b"Cr24"
_VERSION = bytes([3, 0, 0, 0])
_SIG_CONTEXT = b"CRX3 SignedData\x00"


def build_crx3(zip_bytes: bytes, key: dict[str, int]) -> bytes:
    """把 zip 载荷封装成签名后的 CRX3。"""
    spki = spki_der(key["n"], key["e"])
    raw_id = crx_id_raw(spki)

    # SignedData { bytes crx_id = 1; }
    signed_header_data = _pb_bytes(1, raw_id)

    to_sign = (_SIG_CONTEXT
               + len(signed_header_data).to_bytes(4, "little")
               + signed_header_data
               + zip_bytes)
    sig = _pkcs1v15_sha256_sign(key, to_sign)

    # AsymmetricKeyProof { public_key = 1; signature = 2; }
    proof = _pb_bytes(1, spki) + _pb_bytes(2, sig)
    # CrxFileHeader { sha256_with_rsa = 2; signed_header_data = 10000; }
    header = _pb_bytes(2, proof) + _pb_bytes(10000, signed_header_data)

    return _MAGIC + _VERSION + len(header).to_bytes(4, "little") + header + zip_bytes


def parse_crx3(blob: bytes) -> dict[str, Any]:
    """拆开 CRX3，返回各段。测试与自检用。"""
    if blob[:4] != _MAGIC:
        raise ValueError(f"魔数不对：{blob[:4]!r}")
    hlen = int.from_bytes(blob[8:12], "little")
    header = blob[12:12 + hlen]
    zip_bytes = blob[12 + hlen:]
    proof = b""
    signed_header_data = b""
    for field, val in pb_fields(header):
        if field == 2:
            proof = val
        elif field == 10000:
            signed_header_data = val
    public_key = b""
    signature = b""
    for field, val in pb_fields(proof):
        if field == 1:
            public_key = val
        elif field == 2:
            signature = val
    return {
        "version": blob[4:8],
        "header_len": hlen,
        "header": header,
        "zip": zip_bytes,
        "public_key": public_key,
        "signature": signature,
        "signed_header_data": signed_header_data,
    }


def signed_payload(signed_header_data: bytes, zip_bytes: bytes) -> bytes:
    """重建被签名的数据（验签用）。"""
    return (_SIG_CONTEXT
            + len(signed_header_data).to_bytes(4, "little")
            + signed_header_data
            + zip_bytes)


# --------------------------------------------------------------------------- #
# 打包
# --------------------------------------------------------------------------- #
def zip_extension(ext_dir: str | Path) -> bytes:
    """把扩展目录打成 zip（``manifest.json`` 在根，Chrome 要求）。"""
    ext_dir = Path(ext_dir)
    if not (ext_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"扩展目录缺少 manifest.json：{ext_dir}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(ext_dir.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(ext_dir).as_posix())
    return buf.getvalue()


def update_manifest_xml(app_id: str, version: str, crx_url: str) -> str:
    """Chrome 自托管更新清单。策略里的 update_url 指向这个 XML。"""
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>\n"
        f"  <app appid='{app_id}'>\n"
        f"    <updatecheck codebase='{crx_url}' version='{version}' />\n"
        "  </app>\n"
        "</gupdate>\n"
    )
