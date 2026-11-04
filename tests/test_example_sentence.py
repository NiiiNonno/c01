"""利用者の例文を、打鍵列どおりに打って確かめる。"""

from __future__ import annotations

from c01.core import Mode
from c01.session import Key, Session

# 元の例の `ro-ma` は、仕様の片仮名の合図に合わせて `-ro-ma` とした（ローマ字のローマ）
KEYS = (
    "hdi fa tca hjhne,firaganafa ynib fbrlb no -ro-ma jnd oh ks de,"
    "etlo jnd fa oiar grmbc jjomn oh egi de oh ks siteirunodesu "
)
EXPECTED = "私は普段、ひらがなは通常のローマ字入力で、漢字は倉頡輸入法で入力しているのです"


def run(compiled, cfg, keys):
    s = Session(compiled, cfg, Mode.HANWA_HIRA)
    out = []
    for ch in keys:
        key = Key(name="space", char=" ") if ch == " " else Key(char=ch)
        r = s.handle(key)
        assert not r.error, f"{ch!r} の直前で解釈できなかった: buf={s.buf!r}"
        out.append(r.commit)
    return "".join(out)


def test_user_example_with_priority_list(user_compiled_prio, user_cfg_prio):
    """法(egi)を漢字優先リストに入れておけば、例文がそのまま打てる。"""
    assert run(user_compiled_prio, user_cfg_prio, KEYS) == EXPECTED


def test_egi_is_ambiguous_without_priority_entry(user_compiled, user_cfg):
    """リストに無いと、仮名優先の決まりどおり えぎ が先に出る（法は2番目）。"""
    s = Session(user_compiled, user_cfg, Mode.HANWA_HIRA)
    for ch in "egi":
        s.handle(Key(char=ch))
    assert s.cands[:2] == ["えぎ", "法"]


def test_example_everything_else_resolves_without_priority(user_compiled, user_cfg):
    """法以外は、特別な設定なしで第0候補が正しい。"""
    got = run(user_compiled, user_cfg, KEYS)
    assert got == EXPECTED.replace("輸入法", "輸入えぎ")
