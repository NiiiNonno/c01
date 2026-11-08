"""利用者の例文を、新しい仕様（首辞・z による仮名選択）で打鍵列どおりに打って確かめる。

元の例は 仮名を続けて打っていたが、新しい仕様では、首辞リストにない仮名のまとまりは末尾に z を付けて選ぶ。
  ひらがなは → firaganafaz   ローマ → ro-maz   しているのです → siteirunodesuz
は・の・で は首辞リスト（tests/conftest.py の user_kana.txt）に入れてある。
"""

from __future__ import annotations

from c01.core import Mode
from c01.session import Key, Session

KEYS = (
    "hdi fa tca hjhne,firaganafaz ynib fbrlb no ro-maz jnd oh ks de,"
    "etlo jnd fa oiar grmbc jjomn oh egi de oh ks siteirunodesuz "
)
EXPECTED = "私は普段、ひらがなは通常のローマ字入力で、漢字は倉頡輸入法で入力しているのです"


def run(compiled, cfg, keys):
    s = Session(compiled, cfg, Mode.HANWA)
    out = []
    for ch in keys:
        key = Key(name="space", char=" ") if ch == " " else Key(char=ch)
        r = s.handle(key)
        assert not r.error, f"{ch!r} の直前で解釈できなかった: buf={s.buf!r}"
        out.append(r.commit)
    return "".join(out)


def test_user_example(user_compiled, user_cfg):
    assert run(user_compiled, user_cfg, KEYS) == EXPECTED


def test_kana_head_needs_whitelist(user_compiled, user_cfg):
    """首辞リストに入れた は は fa で打てるが、入れていない ひ は fi では打てない（z で選ぶ）。"""
    s = Session(user_compiled, user_cfg, Mode.HANWA)
    for ch in "fa":
        s.handle(Key(char=ch))
    assert s.cands[0] == "は"
    s.reset()
    for ch in "fi":
        s.handle(Key(char=ch))
    assert s.cands[0] != "ひ" and s.cands[-1] == "ひ"
    s.reset()
    for ch in "fiz":
        s.handle(Key(char=ch))
    assert s.cands == ["ひ", "ヒ"]


def test_without_whitelist_kana_loses_to_heads():
    """の が首辞リストに無ければ no は 弓人 系の字が先になる（仕様どおり。リストで調整する）。"""
    from c01.config import Config
    from c01.tables import compile_tables

    cfg = Config(romaji="user", compound=[])
    s = Session(compile_tables(cfg), cfg, Mode.HANWA)
    for ch in "no":
        s.handle(Key(char=ch))
    assert s.cands[0] != "の" and s.cands[-1] == "の"
