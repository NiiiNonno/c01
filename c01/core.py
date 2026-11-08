"""打鍵列の解釈（バッファ → 候補）。ibus には依存しない。

考え方: どの打鍵列も「首辞」から始まり、そのあとに「尾辞」（仮名）が続く。

  首辞 = head の字（倉頡）／ compound の項目（熟語・送り仮名・首辞となる仮名）／ 空文字
  尾辞 = 仮名表（平仮名か片仮名）で最後まで読める仮名の連なり

候補は、首辞に使う打鍵の長さが長いものから順に並ぶ。同じ長さなら compound、head、空首辞の順。
同じ並びの中では、表に書いてある順。仮名だから優先される、ということはない。
空首辞（尾辞だけ）が最下位になる。

末尾が z の打鍵列は、z を外した残りを仮名表で読んだ平仮名と片仮名だけが候補になる。
"""

from __future__ import annotations

from enum import Enum

from .kana import parse_kana
from .tables import Compiled

__all__ = ["Mode", "MODE_ORDER", "MODE_LABELS", "Interpreter", "parse_kana"]

PURE_KEY = "z"  # 末尾に付けると、仮名（平仮名・片仮名）だけを候補にするキー


class Mode(str, Enum):
    DIRECT = "direct"
    KANJI = "kanji"
    HANWA = "hanwa"


MODE_ORDER = [Mode.DIRECT, Mode.KANJI, Mode.HANWA]

MODE_LABELS = {
    Mode.DIRECT: "直",
    Mode.KANJI: "漢",
    Mode.HANWA: "和",
}


class Interpreter:
    def __init__(self, compiled: Compiled, max_split_kanji: int = 3):
        self.c = compiled
        self.max_split_kanji = max_split_kanji

    def _pure_kana(self, base: str) -> list[str]:
        c = self.c
        if not base:
            return []
        out: list[str] = []
        for table, maxlen in ((c.hira, c.hira_max), (c.kata, c.kata_max)):
            k = parse_kana(table, maxlen, base)
            if k and k not in out:
                out.append(k)
        return out

    def candidates(self, buf: str, mode: Mode) -> list[str]:
        if not buf or mode is Mode.DIRECT:
            return []
        c = self.c

        if buf.endswith(PURE_KEY):
            return [] if mode is Mode.KANJI else self._pure_kana(buf[:-1])

        kanji_only = mode is Mode.KANJI
        tail, tmax = c.tail, c.tail_max
        n = len(buf)
        out: list[str] = []
        seen: set[str] = set()

        def add(text: str) -> None:
            if text not in seen:
                seen.add(text)
                out.append(text)

        def tail_of(rest: str) -> str | None:
            if not rest:
                return ""
            if kanji_only:
                return None
            return parse_kana(tail, tmax, rest)

        for L in range(n, 0, -1):
            stroke = buf[:L]
            # 複合首辞（熟語・送り仮名・首辞となる仮名）
            for text, pushback, has_kana in c.compound.get(stroke, ()):
                if kanji_only and has_kana:
                    continue
                t = tail_of(pushback + buf[L:])
                if t is not None:
                    add(text + t)
            # 首辞の字（倉頡など）。尾辞が続く場合は、1つの長さにつき出す字の数を絞る
            taken = 0
            for ch in c.heads.get(stroke, ()):
                t = tail_of(buf[L:])
                if t is None:
                    break
                add(ch + t)
                taken += 1
                if L < n and taken >= self.max_split_kanji:
                    break

        # 空の首辞（尾辞だけ）が最下位
        if not kanji_only:
            t = parse_kana(tail, tmax, buf)
            if t is not None:
                add(t)
        return out
