"""仮名まわりの小さな道具: ローマ字表での読み取り、文字種の判定、平仮名⇔片仮名の変換。"""

from __future__ import annotations


def parse_kana(table: dict[str, tuple[str, str]], maxlen: int, s: str) -> str | None:
    """ローマ字を仮名に直す。全部読めたら仮名、読めなければ None。

    各位置で長い入力から試し、行き止まりになったら短いものに戻る。
    「出力後に残す入力」は、出力のあとで先頭に戻して読み直す
    （例: kk → っ + 残り k。促音は次の子音を残すことで表す）。
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


def script_of(ch: str) -> str:
    """'h' 平仮名 / 'k' 片仮名 / '' それ以外（漢字・記号など）。"""
    o = ord(ch)
    if 0x3041 <= o <= 0x309F or 0x1B001 <= o <= 0x1B11F:
        return "h"
    if 0x30A1 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF:
        return "k"
    return ""


def has_kana(s: str) -> bool:
    return any(script_of(c) for c in s)


_H2K = {**{o: o + 0x60 for o in range(0x3041, 0x3097)}, 0x309D: 0x30FD, 0x309E: 0x30FE}
_K2H = {v: k for k, v in _H2K.items()}


def hira_to_kata(s: str) -> str:
    return s.translate(_H2K)


def kata_to_hira(s: str) -> str:
    return s.translate(_K2H)
