from __future__ import annotations

import pytest

from c01.core import Interpreter, Mode, parse_kana, replace_longest


@pytest.fixture(scope="module")
def interp(hepburn_compiled):
    return Interpreter(hepburn_compiled)


# ---- 仮名の読み取り ------------------------------------------------------

def test_parse_kana_basic(hepburn_compiled):
    c = hepburn_compiled
    assert parse_kana(c.hira, c.hira_max, "kana") == "かな"
    assert parse_kana(c.hira, c.hira_max, "kanji") == "かんじ"
    assert parse_kana(c.hira, c.hira_max, "onna") == "おんな"  # n + na ではなく ん + な
    assert parse_kana(c.hira, c.hira_max, "matcha") is None  # cha は拗音なので平仮名用には無い


def test_parse_kana_sokuon_keeps_next_key(hepburn_compiled):
    c = hepburn_compiled
    assert parse_kana(c.hira, c.hira_max, "kka") == "っか"
    assert parse_kana(c.hira, c.hira_max, "sasshi") == "さっし"  # ss → っ、残った s と hi ではなく shi
    assert parse_kana(c.hira, c.hira_max, "kekkon") == "けっこん"


def test_parse_kana_rejects_incomplete(hepburn_compiled):
    c = hepburn_compiled
    assert parse_kana(c.hira, c.hira_max, "k") is None
    assert parse_kana(c.hira, c.hira_max, "hdi") is None
    assert parse_kana(c.hira, c.hira_max, "") == ""


def test_hiragana_table_has_no_contracted_sounds(hepburn_compiled):
    """平仮名用に kya は無い（拗音は lya などでのみ入力）。"""
    c = hepburn_compiled
    assert parse_kana(c.hira, c.hira_max, "kya") is None
    assert parse_kana(c.hira, c.hira_max, "kilya") == "きゃ"
    assert parse_kana(c.kata, c.kata_max, "kya") == "キャ"


def test_replace_longest():
    assert replace_longest({"あ": "ア", "い": "イ"}, 1, "あいう") == "アイう"
    assert replace_longest({"きゃ": "キャ", "き": "キ"}, 2, "きゃき") == "キャキ"


# ---- 候補の並び（利用者が示した例） ----------------------------------------

def test_priority_kanji_comes_before_kana(interp):
    """a は 日 が仮名より先。それ以外の同コードの字は仮名のあと。"""
    c = interp.candidates("a", Mode.HANWA_HIRA)
    assert c[:3] == ["日", "あ", "曰"]


def test_ai_kana_first_then_full_kanji_then_split(interp):
    """0:あい, 1:旷（全体が倉頡）, 以降: 日い（貪欲に切った先頭の倉頡＋仮名）"""
    c = interp.candidates("ai", Mode.HANWA_HIRA)
    assert c[0] == "あい"
    assert c[1] == "旷"
    assert "日い" in c
    assert c.index("旷") < c.index("日い")


def test_giru_greedy_order(interp):
    """貪欲（長い倉頡が先）。去る問題は使ってみて判断するので、いまは 坮う が 去る より先でよい。"""
    c = interp.candidates("giru", Mode.HANWA_HIRA)
    assert c[0] == "ぎる"
    assert c.index("坮う") < c.index("去る") < c.index("土いる")


def test_kanji_only_when_not_kana(interp):
    assert interp.candidates("hdi", Mode.HANWA_HIRA)[0] == "私"
    assert interp.candidates("hjhne", Mode.HANWA_HIRA)[0] == "段"


def test_no_interpretation_gives_empty(interp):
    assert interp.candidates("oiargrmbc", Mode.HANWA_HIRA) == []  # 連続倉頡は表で指定されたものだけ
    assert interp.candidates("aq", Mode.HANWA_HIRA) == []  # 倉頡にも仮名にも無い


def test_kanji_mode_ignores_kana(interp):
    c = interp.candidates("a", Mode.KANJI)
    assert c[0] == "日" and "あ" not in c
    assert "かな" not in interp.candidates("kana", Mode.KANJI)


def test_direct_mode_gives_nothing(interp):
    assert interp.candidates("a", Mode.DIRECT) == []


def test_katakana_with_leading_hyphen(interp):
    assert interp.candidates("-katakana", Mode.HANWA_HIRA) == ["カタカナ"]
    assert interp.candidates("-yu-za-", Mode.HANWA_HIRA) == ["ユーザー"]
    assert interp.candidates("-kyaku", Mode.HANWA_HIRA) == ["キャク"]  # 拗音は片仮名用にある


def test_hanwa_kata_replaces_kana_only(interp):
    c = interp.candidates("kono", Mode.HANWA_KATA)
    assert c[0] == "コノ"
    # 漢字を含む候補の仮名部分も片仮名になる
    c = interp.candidates("giru", Mode.HANWA_KATA)
    assert c[0] == "ギル"
    assert "去ル" in c


def test_candidates_have_no_duplicates(interp):
    c = interp.candidates("ai", Mode.HANWA_HIRA)
    assert len(c) == len(set(c))


def test_custom_characters_present(interp):
    """倉頡表に無かった々・ヶを追加した表（custom.csv）が効いている。"""
    assert "々" in interp.candidates("ko", Mode.KANJI)
    assert "ヶ" in interp.candidates("kh", Mode.KANJI)
