"""表の読み込みとコンパイル。

どの表も UTF-8 で、`#` で始まる行と空行は無視する。

  romaji/<方式>/hiragana.csv, katakana.csv : 入力, 出力[, 出力後に残す入力]
  cangjie/<名前>.csv                       : 文字, コード[, first]     （head。上の行ほど優先）
  compound/<名前>.txt                      : 1行に1項目（熟語・送り仮名・首辞となる仮名）。`る*` のような * が使える
  wildcards/<名前>.csv                     : 文字, 展開（`る*` を らりるれろっ に広げる）
  symbols/<名前>.csv                       : キー, 出力
  preedit/<名前>.csv                       : キー, 表示
  variants/<名前>.csv                      : 文字, 分類(common/trad/simp/shin)

【考え方】どの打鍵列も「首辞」から始まり、そのあとに「尾辞」（仮名）が続く。
  首辞 = head の字（倉頡）、または compound の項目、または空文字（空が最下位）
  尾辞 = 仮名表（平仮名か片仮名）で読める仮名の連なり
compound の項目は文字列で書き、打鍵列は、字を倉頡コード・仮名をローマ字表に逆変換して作る。
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, cache_dir, find_data
from .kana import has_kana, parse_kana, script_of

COMPILED_VERSION = 4
MAX_VARIANTS = 24  # 1つの項目から作る打鍵列の最大数
MAX_WILDCARD = 256  # 1つの項目を * で広げる最大数


class TableError(Exception):
    pass


# ---- 読み込み ----------------------------------------------------------------

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
    """コード → 字のリスト。表を並べた順、行の順がそのまま優先順位。"""
    table: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for path in paths:
        for no, row in _rows(path):
            if len(row) < 2:
                raise TableError(f"{path}:{no}: 文字とコードが必要です")
            text, code = row[0], row[1].strip().lower()
            position = row[2].strip().lower() if len(row) > 2 else ""
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


def load_pairs(path: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    for no, row in _rows(path):
        if len(row) < 2:
            raise TableError(f"{path}:{no}: 2列必要です")
        d[row[0]] = row[1]
    return d


def load_compound(path: Path) -> list[tuple[int, str]]:
    """(行番号, 項目) のリスト。1行に1項目で、カンマより後ろは読まない。"""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for no, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            text = line.split(",")[0].strip()
            if text:
                out.append((no, text))
    return out


# ---- ワイルドカード ------------------------------------------------------------

def expand_wildcards(text: str, wc: dict[str, str]) -> tuple[list[str], bool, list[str]]:
    """`る*` のような書き方を展開する。(展開した項目, * があったか, 展開表に無かった文字)"""
    parts: list[list[str]] = []
    missing: list[str] = []
    had = False
    i = 0
    while i < len(text):
        ch = text[i]
        if i + 1 < len(text) and text[i + 1] == "*":
            had = True
            alts = wc.get(ch)
            if alts is None:
                missing.append(ch)
                parts.append([ch])
            else:
                parts.append(list(dict.fromkeys(alts)))
            i += 2
        else:
            parts.append([ch])
            i += 1
    out = []
    for combo in itertools.islice(itertools.product(*parts), MAX_WILDCARD):
        out.append("".join(combo))
    return out, had, missing


# ---- 文字列 → 打鍵列（逆変換） ------------------------------------------------------

def _units(table: dict[str, tuple[str, str]]) -> tuple[dict[str, list[tuple[str, str]]], int]:
    by_out: dict[str, list[tuple[str, str]]] = {}
    for key, (out, nxt) in table.items():
        by_out.setdefault(out, []).append((key, nxt))
    return by_out, max((len(o) for o in by_out), default=0)


def _dedupe(seq):
    return list(dict.fromkeys(seq))


class Reverse:
    """字や仮名の列から、それを打つ打鍵列を作る。"""

    def __init__(self, heads: dict[str, list[str]], hira: dict, kata: dict):
        self.codes: dict[str, list[str]] = {}
        for code, chars in heads.items():
            for ch in chars:
                self.codes.setdefault(ch, []).append(code)
        self.tables = {"h": hira, "k": kata}
        self.units = {"h": _units(hira), "k": _units(kata)}
        self.maxkey = {s: max((len(k) for k in t), default=0) for s, t in self.tables.items()}

    def run(self, text: str, script: str, final: bool) -> list[tuple[str, str]]:
        """同じ種類の仮名の連なり text の打鍵列。[(打鍵列, 残す入力)]

        final=False（あとに仮名以外が続く）のとき、「残す入力」を持つ項目（促音の kk など）は使えない。
        最後の仮名のときだけ、っ を促音の形（tt など）で打てる。
        """
        by_out, maxout = self.units[script]
        table, maxkey = self.tables[script], self.maxkey[script]
        n = len(text)
        memo: dict[int, list[tuple[str, str]]] = {}

        def g(i: int) -> list[tuple[str, str]]:
            if i in memo:
                return memo[i]
            res: list[tuple[str, str]] = []
            for L in range(min(maxout, n - i), 0, -1):
                for key, nxt in by_out.get(text[i : i + L], ()):
                    j = i + L
                    if j == n:
                        if nxt and not final:
                            continue
                        res.append((key, nxt))
                        continue
                    for tail, pb in g(j):
                        if nxt:
                            if tail.startswith(nxt):
                                res.append((key + tail[len(nxt):], pb))
                        else:
                            res.append((key + tail, pb))
            res = _dedupe(res)[: MAX_VARIANTS * 4]
            memo[i] = res
            return res

        out = []
        for stroke, pb in g(0):
            # 前から読み直して、同じ仮名になるものだけ残す（n + a が な と読まれる、のような取り違えを除く）
            if not pb and parse_kana(table, maxkey, stroke) != text:
                continue
            out.append((stroke, pb))
        return out

    def strokes(self, text: str) -> list[tuple[str, str]] | None:
        """項目の打鍵列。打てない文字があれば None。"""
        segs: list[tuple[str, str]] = []  # (種類, 文字列)  種類: h k または ''（1字ずつ）
        for ch in text:
            s = script_of(ch)
            if s and segs and segs[-1][0] == s:
                segs[-1] = (s, segs[-1][1] + ch)
            else:
                segs.append((s, ch))
        results: list[tuple[str, str]] = [("", "")]
        for idx, (s, chunk) in enumerate(segs):
            if s:
                alts = self.run(chunk, s, final=(idx == len(segs) - 1))
            else:
                alts = [(code, "") for code in self.codes.get(chunk, ())]
            if not alts:
                return None
            results = [(a + b, pb) for (a, _), (b, pb) in itertools.product(results, alts)]
            results = _dedupe(results)[:MAX_VARIANTS]
        return results


# ---- コンパイル済みの表 -------------------------------------------------------------

@dataclass
class Compiled:
    version: int = COMPILED_VERSION
    fingerprint: str = ""
    hira: dict[str, tuple[str, str]] = field(default_factory=dict)
    kata: dict[str, tuple[str, str]] = field(default_factory=dict)
    tail_kata: bool = False
    # 打鍵列 → 字（首辞）
    heads: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # 打鍵列 → [(出力, 残す入力, 仮名を含むか)]（複合首辞）
    compound: dict[str, tuple[tuple[str, str, bool], ...]] = field(default_factory=dict)
    symbols: dict[str, str] = field(default_factory=dict)
    preedit_map: dict[str, str] = field(default_factory=dict)
    buffer_chars: frozenset[str] = frozenset()
    warnings: list[str] = field(default_factory=list)

    # 読み込み時に計算する（保存しない）
    hira_max: int = 0
    kata_max: int = 0

    def finalize(self) -> "Compiled":
        self.hira_max = max((len(k) for k in self.hira), default=0)
        self.kata_max = max((len(k) for k in self.kata), default=0)
        return self

    @property
    def tail(self) -> dict[str, tuple[str, str]]:
        return self.kata if self.tail_kata else self.hira

    @property
    def tail_max(self) -> int:
        return self.kata_max if self.tail_kata else self.hira_max


def _source_files(cfg: Config) -> dict[str, Path]:
    files: dict[str, Path] = {
        "hira": find_data(f"romaji/{cfg.hiragana_scheme}/hiragana.csv"),
        "kata": find_data(f"romaji/{cfg.katakana_scheme}/katakana.csv"),
        "symbols": find_data(f"symbols/{cfg.symbols}.csv"),
        "wildcards": find_data(f"wildcards/{cfg.wildcards}.csv"),
    }
    for i, name in enumerate(cfg.head):
        files[f"head{i:03d}"] = find_data(f"cangjie/{name}.csv")
    for i, name in enumerate(cfg.compound):
        files[f"compound{i:03d}"] = find_data(f"compound/{name}.txt")
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
        "hira": cfg.hiragana_scheme, "kata": cfg.katakana_scheme, "tail": cfg.tail,
        "head": cfg.head, "compound": cfg.compound, "wildcards": cfg.wildcards,
        "symbols": cfg.symbols, "variants": cfg.variants, "script": cfg.script,
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
    c.warnings.extend(cfg.notes)

    c.hira = load_romaji(files["hira"])
    c.kata = load_romaji(files["kata"])
    c.tail_kata = cfg.tail == "katakana"

    heads = load_cangjie([files[k] for k in sorted(files) if k.startswith("head")])

    # 字種の絞り込み
    allowed = _allowed_classes(cfg.script)
    klass: dict[str, str] = {}
    if allowed is not None:
        if "variants" not in files:
            c.warnings.append(
                f"script={cfg.script} が指定されていますが、分類表（variants）が未設定のため全部の文字を出します"
            )
            allowed = None
        else:
            klass = load_pairs(files["variants"])

    def char_ok(text: str) -> bool:
        return allowed is None or all(klass.get(ch, "common") in allowed for ch in text)

    if allowed is not None:
        for code, lst in list(heads.items()):
            kept = [t for t in lst if char_ok(t)]
            if kept:
                heads[code] = kept
            else:
                del heads[code]
    c.heads = {k: tuple(v) for k, v in heads.items()}

    # 複合首辞
    wc = load_pairs(files["wildcards"])
    rev = Reverse(heads, c.hira, c.kata)
    compound: dict[str, list[tuple[str, str, bool]]] = {}
    for key in sorted(k for k in files if k.startswith("compound")):
        path = files[key]
        skipped: list[str] = []
        for no, raw in load_compound(path):
            texts, had_star, missing = expand_wildcards(raw, wc)
            for ch in missing:
                c.warnings.append(f"{path.name}:{no}: {ch}* の展開が wildcards 表にありません（{ch} のまま扱います）")
            made_any = False
            for text in texts:
                if not char_ok(text):
                    made_any = True  # 絞り込みで除いたものは、打てないわけではない
                    continue
                strokes = rev.strokes(text)
                if not strokes:
                    continue
                made_any = True
                hk = has_kana(text)
                for stroke, pb in strokes:
                    lst = compound.setdefault(stroke, [])
                    entry = (text, pb, hk)
                    if entry not in lst:
                        lst.append(entry)
            if not made_any:
                skipped.append(raw)
        if skipped:
            shown = "、".join(skipped[:5]) + ("…" if len(skipped) > 5 else "")
            c.warnings.append(
                f"{path.name}: {len(skipped)} 件は、倉頡表か仮名表に無い字があって打鍵列にできず、飛ばしました（{shown}）"
            )
    c.compound = {k: tuple(v) for k, v in compound.items()}

    c.symbols = load_pairs(files["symbols"])
    if "preedit" in files:
        c.preedit_map = load_pairs(files["preedit"])

    # 打鍵として受け取る文字: 仮名表と倉頡のコードに現れる文字、z（仮名の選択）、-
    chars: set[str] = {"-", "z"}
    for t in (c.hira, c.kata):
        for k in t:
            chars.update(k)
    for k in c.heads:
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
        fp = current_fingerprint(cfg)
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
