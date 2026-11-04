"""打鍵列（バッファ）から候補を作る中核部分。ibus には依存しない。

方針（いまは貪欲なマッチング）:
  1. 全体が仮名として読めるか、全体が1つの倉頡コードか、を調べる
  2. 先頭から倉頡コードに「長く」当てはまる順に、残りを仮名として読む（漢字＋仮名）
  3. 仮名で読めたときは 漢字優先リストの漢字 → 仮名 → ほかの漢字 の順

和漢混淆（片）は、仮名を平仮名テーブルで読んだあと、置き換え表で片仮名にする。
"""

from __future__ import annotations

from enum import Enum

from .tables import Compiled


class Mode(str, Enum):
    DIRECT = "direct"
    KANJI = "kanji"
    HANWA_HIRA = "hanwa_hira"
    HANWA_KATA = "hanwa_kata"


MODE_ORDER = [Mode.DIRECT, Mode.KANJI, Mode.HANWA_HIRA, Mode.HANWA_KATA]

MODE_LABELS = {
    Mode.DIRECT: "直",
    Mode.KANJI: "漢",
    Mode.HANWA_HIRA: "和",
    Mode.HANWA_KATA: "ヲ",
}


def parse_kana(table: dict[str, tuple[str, str]], maxlen: int, s: str) -> str | None:
    """ローマ字を仮名にする。全部読めたらその文字列、読めなければ None。

    各位置で長い入力から順に試し、行き止まりになったら短いほうへ戻る。
    「出力後に残す入力」（例: kk → っ + 残り k）は残りの先頭に戻して続きを読む。
    """
    memo: dict[str, str | None] = {}

    def rec(rest: str) -> str | None:
        if not rest:
            return ""
        if rest in memo:
            return memo[rest]
        result = None
        for n in range(min(maxlen, len(rest)), 0, -1):
            entry = table.get(rest[:n])
            if entry is None:
                continue
            out, nxt = entry
            sub = rec(nxt + rest[n:])
            if sub is not None:
                result = out + sub
                break
        memo[rest] = result
        return result

    return rec(s)


def replace_longest(mapping: dict[str, str], maxlen: int, s: str) -> str:
    """置き換え表を左から長い順に当てる。表にない文字はそのまま。"""
    out = []
    i = 0
    while i < len(s):
        for n in range(min(maxlen, len(s) - i), 0, -1):
            r = mapping.get(s[i : i + n])
            if r is not None:
                out.append(r)
                i += n
                break
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


class Interpreter:
    def __init__(self, compiled: Compiled, max_split_kanji: int = 3):
        self.c = compiled
        self.max_split_kanji = max_split_kanji

    # --- 仮名 ---------------------------------------------------------
    def _hira(self, s: str, mode: Mode) -> str | None:
        k = parse_kana(self.c.hira, self.c.hira_max, s)
        if k is not None and mode is Mode.HANWA_KATA:
            k = replace_longest(self.c.hira2kata, self.c.h2k_max, k)
        return k

    # --- 候補 ---------------------------------------------------------
    def candidates(self, buf: str, mode: Mode) -> list[str]:
        if not buf or mode is Mode.DIRECT:
            return []
        c = self.c
        kanji_full = list(c.cangjie.get(buf, ()))

        if mode is Mode.KANJI:
            return kanji_full

        # 片仮名のまとまり: 先頭の '-' が合図（和漢混淆（平）のときだけ）
        if mode is Mode.HANWA_HIRA and buf.startswith("-") and len(buf) > 1:
            kata = parse_kana(c.kata, c.kata_max, buf[1:])
            if kata is not None:
                return [kata]

        out: list[str] = []
        kana = self._hira(buf, mode)
        if kana is not None:
            first = [k for k in kanji_full if k in c.priority]
            later = [k for k in kanji_full if k not in c.priority]
            out += first + [kana] + later
        else:
            out += kanji_full

        # 漢字＋仮名: 先頭から倉頡コードに長く当てはまる順（貪欲）
        for n in range(min(len(buf) - 1, c.cj_max), 0, -1):
            kanji = c.cangjie.get(buf[:n])
            if not kanji:
                continue
            rest = self._hira(buf[n:], mode)
            if rest is None:
                continue
            for k in kanji[: self.max_split_kanji]:
                out.append(k + rest)

        seen: set[str] = set()
        uniq = []
        for t in out:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        return uniq
