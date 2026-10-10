"""只读解析用户指定的影刀 .NET 程序，不加载/执行程序集。

依赖仅放在 build/analysis_deps；输出方法名、调用与筛选后的常量。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build" / "analysis_deps"))
import dnfile
from dncil.cil.body import CilMethodBody
from dncil.cil.body.reader import CilMethodBodyReaderBytes
from dncil.clr.token import Token, StringToken


def inspect(path: Path, pattern: str, strings_only: bool = False, resources: bool = False):
    pe = dnfile.dnPE(str(path))
    print(f"FILE {path}")
    if not pe.net:
        print("not a .NET assembly")
        return
    names = {}
    for type_row in pe.net.mdtables.TypeDef:
        owner = str(type_row.TypeNamespace) + "." + str(type_row.TypeName)
        for method in type_row.MethodList:
            names[method.row_index] = owner + "::" + str(method.row.Name)

    def resolve(token):
        if isinstance(token, StringToken):
            item = pe.net.user_strings.get(token.rid)
            return repr(str(item)) if item else str(token)
        if not isinstance(token, Token):
            return str(token)
        if token.table == 6:
            return names.get(token.rid, str(token))
        table = pe.net.mdtables.tables.get(token.table)
        if table and 0 < token.rid <= len(table.rows):
            row = table.rows[token.rid - 1]
            name = str(getattr(row, "Name", getattr(row, "TypeName", token)))
            parent = getattr(row, "Class", None)
            if parent and getattr(parent, "row", None):
                name = str(getattr(parent.row, "TypeName", "")) + "::" + name
            return name
        return str(token)

    matcher = re.compile(pattern, re.I)
    if resources:
        for resource in pe.net.resources:
            for entry in getattr(resource.data, "entries", []):
                if matcher.search(str(entry.name)) and isinstance(entry.value, str):
                    print("RESOURCE", str(entry.name), repr(entry.value))
    for rid, method in enumerate(pe.net.mdtables.MethodDef, 1):
        name = names.get(rid, str(method.Name))
        if not method.Rva:
            continue
        try:
            body = CilMethodBody(CilMethodBodyReaderBytes(pe.get_data(method.Rva)))
        except Exception:
            continue
        ops = [(str(i.opcode), resolve(i.operand)) for i in body.instructions]
        if not matcher.search(name) and not any(matcher.search(o) for _, o in ops):
            continue
        print("METHOD", name)
        for opcode, operand in ops:
            if strings_only:
                if opcode == "ldstr" and matcher.search(operand):
                    print(" ", operand[:1200])
            elif opcode in ("ldstr", "call", "callvirt", "newobj", "ldftn"):
                print(" ", opcode, operand[:1200])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--pattern", default="Chrome|Extension|Install|XPath|Selector")
    parser.add_argument("--strings-only", action="store_true")
    parser.add_argument("--resources", action="store_true")
    args = parser.parse_args()
    inspect(args.path, args.pattern, args.strings_only, args.resources)
