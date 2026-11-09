"""compound のリスト（セクション形式）の読み込み。

    ; ここは注釈
    [甲]            ← 語群の定義。以下の行がメンバー（1行に1つ）
    日
    木
    [る＃一段]
    ()              ← 空（語尾が無い形）
    る
    れ
    [!HEAD]         ← ! の付いたセクションが compound の項目になる（名前は自由。同じ名前でも別でも、書いた順に連なる）
    (甲)は          ← 甲のメンバーそれぞれに「は」を付けた項目に展開する
    着(る＃一段)    ← 着 着る 着れ …
    必ず

- `(名前)` は、そのファイルの中で、すでに定義した語群のメンバー全部に置き換わる（直積）。
  定義より前の参照・未定義の名前・同名の再定義はエラー。別のファイルの定義は参照できない。
- 語群のメンバーの中にも `(名前)` が書ける（入れ子）。
- `()` は空文字。`(OPEN)` `(CLOSE)` はそれぞれ `(` `)` という文字（定義済み）。
  行頭の `[` `;` が必要なときのために `(LBRACKET)` `(RBRACKET)` `(SEMICOLON)` もある。
- 行の前後の空白は無視する。`;` で始まる行は注釈。
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

MAX_EXPAND = 5000  # 1行が広がる最大数

PREDEFINED = {
    "OPEN": ["("],
    "CLOSE": [")"],
    "LBRACKET": ["["],
    "RBRACKET": ["]"],
    "SEMICOLON": [";"],
}

_REF = re.compile(r"\(([^()]*)\)")
_HEADER = re.compile(r"^\[(!?)([^\[\]]+)\]$")


class SectionError(Exception):
    pass


def _expand(line: str, classes: dict[str, list[str]], where: str) -> list[str]:
    parts: list[list[str]] = []
    pos = 0
    for m in _REF.finditer(line):
        if m.start() > pos:
            parts.append([line[pos : m.start()]])
        name = m.group(1)
        if name == "":
            parts.append([""])
        elif name in classes:
            parts.append(classes[name])
        else:
            raise SectionError(
                f"{where}: ({name}) は定義されていません（参照はそのファイルの中で、先に定義したものだけ）"
            )
        pos = m.end()
    if pos < len(line):
        rest = line[pos:]
        if "(" in rest or ")" in rest:
            raise SectionError(f"{where}: 括弧が対応していません。括弧の文字は (OPEN) (CLOSE) で書きます")
        parts.append([rest])
    out: list[str] = []
    for combo in itertools.islice(itertools.product(*parts), MAX_EXPAND + 1):
        out.append("".join(combo))
    if len(out) > MAX_EXPAND:
        raise SectionError(f"{where}: 1行が {MAX_EXPAND} 件を超えて広がります。語群を分けてください")
    return list(dict.fromkeys(out))


def load_sections(path: Path) -> list[tuple[int, str, str]]:
    """出力セクション（[!…]）の項目を、展開して (行番号, セクション名, 文字列) で返す。"""
    classes: dict[str, list[str]] = {k: list(v) for k, v in PREDEFINED.items()}
    current: tuple[str, bool] | None = None  # (名前, 出力か)
    items: list[tuple[int, str, str]] = []
    defined_here: set[str] = set()
    with open(path, encoding="utf-8-sig") as f:
        for no, raw in enumerate(f, start=1):
            line = raw.strip()
            where = f"{path.name}:{no}"
            if not line or line.startswith(";"):
                continue
            m = _HEADER.match(line)
            if m:
                out, name = bool(m.group(1)), m.group(2).strip()
                if not name:
                    raise SectionError(f"{where}: セクションの名前が空です")
                if not out:
                    if name in PREDEFINED:
                        raise SectionError(f"{where}: [{name}] は定義済みの名前なので、定義し直せません")
                    if name in defined_here:
                        raise SectionError(f"{where}: [{name}] はすでに定義されています")
                    defined_here.add(name)
                    classes[name] = []
                current = (name, out)
                continue
            if line.startswith("["):
                raise SectionError(f"{where}: セクション名の書き方が正しくありません: {line!r}")
            if current is None:
                raise SectionError(f"{where}: 最初のセクション（[名前]）より前に項目があります")
            name, out = current
            expanded = _expand(line, classes, where)
            if out:
                for text in expanded:
                    if text:
                        items.append((no, name, text))
            else:
                classes[name].extend(t for t in expanded if t not in classes[name])
    return items
