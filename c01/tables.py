"""CSV テーブルの読み込みとコンパイル。

どのテーブルも UTF-8 の CSV で、`#` で始まる行と空行は無視する。

  romaji/<方式>/hiragana.csv, katakana.csv : 入力, 出力[, 出力後に残す入力]
  cangjie/<名前>.csv                       : 文字, コード[, 位置(first/last)]   （上の行ほど優先）
  symbols/<名前>.csv                       : キー, 出力
  priority/<名前>.csv                      : 文字（仮名より先に出す漢字）
  hira2kata/<名前>.csv                     : 平仮名, 片仮名
  preedit/<名前>.csv                       : キー, 表示
  variants/<名前>.csv                      : 文字, 分類(common/trad/simp/shin)
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, cache_dir, find_data

COMPILED_VERSION = 3


class TableError(Exception):
    pass


def _rows(path: Path):
    """(行番号, 列のリスト) を返す。コメント行・空行は飛ばす。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        for no, row in enumerate(csv.reader(f), start=1):
            if not row or not row[0].strip():
                continue
            if row[0].lstrip().startswith("#"):
                continue
            yield no, row


def load_romaji(path: Path) -> dict[str, tuple[str, str]]:
    table: dict[str, tuple[str, str]] = {}
    for no, row in _rows(path):
        key = row[0]
        out = row[1] if len(row) > 1 else ""
        nxt = row[2] if len(row) > 2 else ""
        if not key or not out:
            raise TableError(f"{path}:{no}: 入力と出力の両方が必要です")
        if len(nxt) >= len(key):
            raise TableError(
                f"{path}:{no}: 「出力後に残す入力」{nxt!r} は入力 {key!r} より短くしてください"
                "（無限に繰り返してしまうため）"
            )
        table[key] = (out, nxt)  # 同じ入力が複数あれば後の行が勝つ
    return table


def load_cangjie(paths: list[Path]) -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for path in paths:
        for no, row in _rows(path):
            if len(row) < 2:
                raise TableError(f"{path}:{no}: 文字とコードが必要です")
            text, code = row[0], row[1].strip().lower()
            position = row[2].strip().lower() if len(row) > 2 else ""
            # 3列目は第一の表（本体）では注記が入っていることがあるので first だけ見る
            if not text or not code:
                raise TableError(f"{path}:{no}: 文字とコードが必要です")
            if (code, text) in seen:
                continue
            seen.add((code, text))
            lst = table.setdefault(code, [])
            if position == "first":
                lst.insert(0, text)
            else:
                lst.append(text)
    return table


def load_priority(path: Path) -> frozenset[str]:
    return frozenset(row[0].strip() for _, row in _rows(path))


def load_pairs(path: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    for no, row in _rows(path):
        if len(row) < 2:
            raise TableError(f"{path}:{no}: 2列必要です")
        d[row[0]] = row[1]
    return d


@dataclass
class Compiled:
    version: int = COMPILED_VERSION
    fingerprint: str = ""
    hira: dict[str, tuple[str, str]] = field(default_factory=dict)
    kata: dict[str, tuple[str, str]] = field(default_factory=dict)
    cangjie: dict[str, tuple[str, ...]] = field(default_factory=dict)
    priority: frozenset[str] = frozenset()
    hira2kata: dict[str, str] = field(default_factory=dict)
    symbols: dict[str, str] = field(default_factory=dict)
    preedit_map: dict[str, str] = field(default_factory=dict)
    buffer_chars: frozenset[str] = frozenset()
    warnings: list[str] = field(default_factory=list)

    # 以下は読み込み時に計算する（保存しない）
    hira_max: int = 0
    kata_max: int = 0
    cj_max: int = 0
    h2k_max: int = 0

    def finalize(self) -> "Compiled":
        self.hira_max = max((len(k) for k in self.hira), default=0)
        self.kata_max = max((len(k) for k in self.kata), default=0)
        self.cj_max = max((len(k) for k in self.cangjie), default=0)
        self.h2k_max = max((len(k) for k in self.hira2kata), default=0)
        return self


def _source_files(cfg: Config) -> dict[str, Path]:
    files: dict[str, Path] = {
        "hira": find_data(f"romaji/{cfg.romaji}/hiragana.csv"),
        "kata": find_data(f"romaji/{cfg.romaji}/katakana.csv"),
        "cangjie": find_data(f"cangjie/{cfg.cangjie}.csv"),
        "symbols": find_data(f"symbols/{cfg.symbols}.csv"),
        "priority": find_data(f"priority/{cfg.kanji_priority}.csv"),
        "hira2kata": find_data(f"hira2kata/{cfg.hira2kata}.csv"),
    }
    for i, name in enumerate(cfg.cangjie_extra):
        files[f"cangjie_extra{i}"] = find_data(f"cangjie/{name}.csv")
    if cfg.preedit == "map":
        files["preedit"] = find_data(f"preedit/{cfg.preedit_map}.csv")
    if cfg.variants:
        files["variants"] = find_data(f"variants/{cfg.variants}.csv")
    return files


def _fingerprint(cfg: Config, files: dict[str, Path]) -> str:
    h = hashlib.sha256()
    h.update(str(COMPILED_VERSION).encode())
    # 実行に関わる項目だけ（モード・キー・音などは再コンパイル不要）
    relevant = {
        "romaji": cfg.romaji, "symbols": cfg.symbols, "cangjie": cfg.cangjie,
        "extra": cfg.cangjie_extra, "priority": cfg.kanji_priority,
        "hira2kata": cfg.hira2kata, "variants": cfg.variants, "script": cfg.script,
        "preedit": cfg.preedit, "preedit_map": cfg.preedit_map,
    }
    h.update(json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode())
    for k in sorted(files):
        p = files[k]
        st = p.stat()
        h.update(f"{k}:{p}:{st.st_mtime_ns}:{st.st_size}".encode())
    return h.hexdigest()


def _allowed_classes(script: str) -> set[str] | None:
    if script == "all":
        return None
    return {"common", script}


def compile_tables(cfg: Config) -> Compiled:
    files = _source_files(cfg)
    c = Compiled(fingerprint=_fingerprint(cfg, files))

    c.hira = load_romaji(files["hira"])
    c.kata = load_romaji(files["kata"])

    cj_paths = [files["cangjie"]] + [files[k] for k in sorted(files) if k.startswith("cangjie_extra")]
    cangjie = load_cangjie(cj_paths)

    allowed = _allowed_classes(cfg.script)
    if allowed is not None:
        if "variants" not in files:
            c.warnings.append(
                f"script={cfg.script} が指定されていますが、分類表（variants）が未設定のため全部の文字を出します"
            )
        else:
            klass = load_pairs(files["variants"])
            for code, lst in list(cangjie.items()):
                kept = [t for t in lst if all(klass.get(ch, "common") in allowed for ch in t)]
                if kept:
                    cangjie[code] = kept
                else:
                    del cangjie[code]
    c.cangjie = {k: tuple(v) for k, v in cangjie.items()}

    c.priority = load_priority(files["priority"])
    c.hira2kata = load_pairs(files["hira2kata"])
    c.symbols = load_pairs(files["symbols"])
    if "preedit" in files:
        c.preedit_map = load_pairs(files["preedit"])

    # 打鍵として受け取る文字: 仮名テーブルと倉頡のコードに現れる文字（と '-'）
    chars: set[str] = {"-"}
    for t in (c.hira, c.kata):
        for k in t:
            chars.update(k)
    for k in c.cangjie:
        chars.update(k)
    c.buffer_chars = frozenset(chars)

    # 記号テーブルのキーが打鍵に使われる文字と重なる場合は、打鍵を優先する
    for k in list(c.symbols):
        if len(k) != 1:
            c.warnings.append(f"記号テーブルのキー {k!r} は1文字ではないので無視します")
            del c.symbols[k]
        elif k in c.buffer_chars:
            c.warnings.append(f"記号テーブルのキー {k!r} は仮名・倉頡の入力に使われているため無視します")
            del c.symbols[k]
    return c.finalize()


def current_fingerprint(cfg: Config) -> str:
    """いまのCSVと設定から作った指紋。コンパイル済みの表と違えば、作り直しが必要。"""
    return _fingerprint(cfg, _source_files(cfg))


def cache_path() -> Path:
    return cache_dir() / "compiled.pickle"


def save_compiled(c: Compiled) -> None:
    p = cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(c, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, p)
    except OSError:
        pass  # キャッシュは無くても動く


def load_or_compile(cfg: Config, force: bool = False) -> Compiled:
    """コンパイル済みの表を読む。元のCSVや設定が変わっていれば作り直す。"""
    if not force:
        files = _source_files(cfg)
        fp = _fingerprint(cfg, files)
        try:
            with open(cache_path(), "rb") as f:
                c = pickle.load(f)
            if isinstance(c, Compiled) and c.version == COMPILED_VERSION and c.fingerprint == fp:
                return c.finalize()
        except Exception:
            pass
    c = compile_tables(cfg)
    save_compiled(c)
    return c
