"""外部の倉頡データを C01 の CSV に変換する。

対応: Jackchows/Cangjie5 の Cangjie5*.txt（「漢字<TAB>倉頡碼<TAB>標註」の形式）。
行の順がそのまま優先順位になる。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

_CODE = re.compile(r"^[a-z]+$")


def import_cangjie5_txt(src: Path, dst: Path, keep_z: bool = False) -> tuple[int, int]:
    """(書いた行数, 飛ばした行数) を返す。"""
    kept = skipped = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8", newline="") as g:
        w = csv.writer(g, lineterminator="\n")
        g.write("# 文字,コード  （上の行ほど優先）。Cangjie5 (MIT License) から変換。LICENSE-Cangjie5.txt 参照\n")
        for line in f:
            line = line.rstrip("\n")
            parts = line.split("\t")
            if len(parts) < 2 or not parts[0] or not _CODE.match(parts[1]):
                skipped += 1
                continue
            text, code = parts[0], parts[1]
            if code.startswith("z") and not keep_z:
                skipped += 1  # 兼容漢字・部首・記号などの特殊コード
                continue
            w.writerow([text, code])
            kept += 1
    return kept, skipped
