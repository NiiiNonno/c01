from __future__ import annotations

import pytest

from c01.config import Config
from c01.core import Interpreter, Mode, parse_kana
from c01.tables import compile_tables
from conftest import write_csv


@pytest.fixture(scope="module")
def interp(hepburn_compiled):
    return Interpreter(hepburn_compiled)


def cands(interp, buf, mode=Mode.HANWA):
    return interp.candidates(buf, mode)


# ---- 仮名の読み取り（尾辞・z の部品） ----------------------------------------

def test_parse_kana_basic(hepburn_compiled):
    c = hepburn_compiled
    assert parse_kana(c.hira, c.hira_max, "kana") == "かな"
    assert parse_kana(c.hira, c.hira_max, "onna") == "おんな"  # n + na ではなく ん + な
    assert parse_kana(c.hira, c.hira_max, "kekkon") == "けっこん"
    assert parse_kana(c.hira, c.hira_max, "k") is None
    assert parse_kana(c.hira, c.hira_max, "") == ""


def test_hiragana_table_has_no_contracted_sounds_or_hyphen(hepburn_compiled):
    c = hepburn_compiled
    assert parse_kana(c.hira, c.hira_max, "kya") is None
    assert parse_kana(c.hira, c.hira_max, "kilya") == "きゃ"
    assert parse_kana(c.hira, c.hira_max, "yu-za-") is None  # ー は平仮名表に無い
    assert parse_kana(c.kata, c.kata_max, "kya") == "キャ"


# ---- 長さで決まる（仮名だから優先、ということはない） ----------------------------

def test_whitelisted_kana_wins_only_on_equal_length(interp):
    """ni: 同じ長さなら compound（に）が head（夕）に勝つ。"""
    c = cands(interp, "ni")
    assert c[0] == "に" and c[1] == "夕"


def test_longer_head_char_beats_whitelisted_kana(interp):
    """niyo: 4打鍵の癶 が、に+よ（2打鍵の首辞）より先。"""
    c = cands(interp, "niyo")
    assert c[0] == "癶"
    assert c.index("癶") < c.index("によ")


def test_longer_whitelisted_entries_win(interp):
    assert cands(interp, "niyoru")[0] == "による"
    assert cands(interp, "niyotte")[0] == "によって"


def test_kana_not_in_whitelist_is_not_preferred(interp):
    """a は日。あ はリストに無いので、漢字のあと（空首辞なので最下位）。"""
    c = cands(interp, "a")
    assert c[:2] == ["日", "曰"]
    assert c[-1] == "あ"


def test_empty_head_is_lowest(interp):
    """全体が仮名として読めても、空の首辞は最下位。"""
    c = cands(interp, "ai")
    assert c[0] == "旷" and c[-1] == "あい"
    assert "日い" in c and c.index("日い") < c.index("あい")


def test_no_duplicates(interp):
    c = cands(interp, "ni")
    assert len(c) == len(set(c))


# ---- 去る問題 ---------------------------------------------------------------

def test_okurigana_list_fixes_saru(interp):
    c = cands(interp, "giru")
    assert c[0] == "去る"
    assert c.index("去る") < c.index("坮う")
    assert c[-1] == "ぎる"


def test_okurigana_wildcard_forms(interp):
    assert cands(interp, "gira")[0] == "去ら"
    assert cands(interp, "giri")[0] == "去り"
    assert cands(interp, "gire")[0] == "去れ"


def test_okurigana_with_geminate_then_tail(interp):
    """去っ（促音の形 tt で終わる首辞）のあとに尾辞 て が続く: gitte → 去って"""
    assert cands(interp, "gitte")[0] == "去って"


def test_head_then_tail_still_works(interp):
    c = cands(interp, "gitte")
    assert "去って" in c


# ---- 熟語・連続した倉頡・漢かな字 ---------------------------------------------------

def test_consecutive_cangjie_from_jukugo(interp):
    assert cands(interp, "oiargrmbc") == ["倉頡"]
    assert cands(interp, "oiargrmbc", Mode.KANJI) == ["倉頡"]


def test_mixed_entries_round_trip(hepburn_compiled):
    """熟語リストの「真ん中」「ラ行」「その他」「真っ当」を、逆変換した打鍵列で打てる。"""
    from c01.tables import Reverse

    interp = Interpreter(hepburn_compiled)
    rev = Reverse(
        {k: list(v) for k, v in hepburn_compiled.heads.items()}, hepburn_compiled.hira, hepburn_compiled.kata
    )
    for word in ("真ん中", "ラ行", "その他", "真っ当"):
        strokes = rev.strokes(word)
        assert strokes, word
        stroke, pb = strokes[0]
        assert not pb
        assert interp.candidates(stroke, Mode.HANWA)[0] == word, (word, stroke)


def test_nn_vowel_ambiguity_is_filtered(hepburn_compiled):
    """ほんの を ho+n+no = hono と打つと ほの と読まれてしまうので、その打鍵列は作らない。"""
    from c01.tables import Reverse

    rev = Reverse({}, hepburn_compiled.hira, hepburn_compiled.kata)
    strokes = [s for s, _ in rev.strokes("ほんの")]
    assert strokes and "hono" not in strokes
    assert "hon'no" in strokes


def test_small_tsu_before_kanji_needs_standalone_entry(tmp_path, monkeypatch):
    """っ<漢字> は、単独で っ を打てる入力が仮名表にあるときだけ。"""
    monkeypatch.setenv("C01_DATA_DIR", str(tmp_path))
    write_csv(tmp_path / "romaji/mini/hiragana.csv", [("ta", "た"), ("tt", "っ", "t"), ("to", "と")])
    write_csv(tmp_path / "romaji/mini/katakana.csv", [("ta", "タ")])
    write_csv(tmp_path / "cangjie/mini.csv", [("真", "ab"), ("当", "cd")])
    (tmp_path / "compound").mkdir()
    (tmp_path / "compound/m.txt").write_text("真っ当\n", encoding="utf-8")
    cfg = Config(romaji="mini", head=["mini"], compound=["m"])
    c = compile_tables(cfg)
    assert c.compound == {}  # tt は「次の子音を残す」形なので、漢字の前には使えない
    assert any("真っ当" in w for w in c.warnings)

    write_csv(tmp_path / "romaji/mini/hiragana.csv", [("ta", "た"), ("tt", "っ", "t"), ("ltu", "っ"), ("to", "と")])
    c = compile_tables(cfg)
    assert list(c.compound) == ["abltucd"]
    assert Interpreter(c).candidates("abltucd", Mode.HANWA)[0] == "真っ当"


# ---- z（仮名の選択） ---------------------------------------------------------

def test_z_gives_hiragana_then_katakana_only(interp):
    assert cands(interp, "kanaz") == ["かな", "カナ"]


def test_z_with_hyphen_is_katakana_only(interp):
    assert cands(interp, "yu-za-z") == ["ユーザー"]


def test_z_with_contracted_sound_is_katakana_only(interp):
    assert cands(interp, "kyaz") == ["キャ"]


def test_z_alone_or_unreadable_is_empty(interp):
    assert cands(interp, "z") == []
    assert cands(interp, "qqz") == []


def test_z_ignores_heads_and_compounds(interp):
    """末尾が z なら、倉頡や首辞リストは候補に出ない。"""
    assert cands(interp, "niz") == ["に", "ニ"]


def test_hyphen_alone_is_not_special(interp):
    """- は、先頭でもただの長音（片仮名表の ー）。片仮名にするのは z だけ。"""
    assert cands(interp, "-katakana") == []
    assert cands(interp, "katakanaz") == ["かたかな", "カタカナ"]
    assert cands(interp, "-katakanaz") == ["ーカタカナ"]


# ---- モード ------------------------------------------------------------------

def test_kanji_mode_has_no_kana(interp):
    assert cands(interp, "giru", Mode.KANJI) == []  # 去る には仮名が入る
    assert cands(interp, "kanaz", Mode.KANJI) == []
    assert cands(interp, "hdi", Mode.KANJI)[0] == "私"
    assert "あい" not in cands(interp, "ai", Mode.KANJI)


def test_direct_mode_gives_nothing(interp):
    assert cands(interp, "a", Mode.DIRECT) == []


def test_unreadable_gives_empty(interp):
    assert cands(interp, "aq") == []
    assert cands(interp, "aqaq") == []


def test_tail_katakana_is_wakan_konkou_kata(hepburn_compiled):
    """tail を片仮名にすると、首辞のあとの仮名が片仮名になる（和漢混淆・片）。"""
    c = compile_tables(Config(tail="katakana"))
    it = Interpreter(c)
    assert it.candidates("giu", Mode.HANWA)[:1] == ["去ウ"]
    assert "去ク" in it.candidates("giku", Mode.HANWA)  # gi + ku の ku が片仮名になる
    assert not any("去く" in t for t in it.candidates("giku", Mode.HANWA))
    # 空首辞（尾辞だけ）も片仮名表で読む
    assert it.candidates("kyaku", Mode.HANWA)[-1] == "キャク"


# ---- 追加字・段階的な絞り込み ----------------------------------------------------

def test_custom_characters_present(interp):
    assert "々" in cands(interp, "ko", Mode.KANJI)
    assert "ヶ" in cands(interp, "kh", Mode.KANJI)


def test_max_split_limits_only_partial_matches(hepburn_compiled):
    few = Interpreter(hepburn_compiled, max_split_kanji=1)
    many = Interpreter(hepburn_compiled, max_split_kanji=3)
    assert len(few.candidates("niyo", Mode.HANWA)) < len(many.candidates("niyo", Mode.HANWA))
    # 全体が1字で読める候補は絞られない
    assert few.candidates("a", Mode.HANWA)[:2] == ["日", "曰"]
