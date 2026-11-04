from __future__ import annotations

import pytest

from c01.config import Config
from c01.core import Mode
from c01.session import Key, Session


def make(compiled, mode=Mode.HANWA_HIRA, **cfg):
    return Session(compiled, Config(**cfg), mode)


def typed(s: Session, keys: str):
    """文字列を1文字ずつ打つ。確定された文字を集めて返す。"""
    out = []
    for ch in keys:
        key = Key(name="space", char=" ") if ch == " " else Key(char=ch)
        r = s.handle(key)
        out.append(r.commit)
    return "".join(out)


def press(s: Session, name: str, **mods):
    return s.handle(Key(name=name, **mods))


@pytest.fixture
def s(hepburn_compiled):
    return make(hepburn_compiled)


def test_space_commits_first_candidate(s):
    assert typed(s, "a ") == "日"
    assert s.buf == ""


def test_second_candidate_by_down_arrow_then_space(s):
    typed(s, "a")
    assert s.cands[:2] == ["日", "あ"]
    press(s, "Down")
    assert s.cursor == 1
    assert press(s, "space").commit == "あ"


def test_digit_selects_on_current_page(s):
    typed(s, "a")
    r = s.handle(Key(char="1"))
    assert r.commit == "あ"


def test_digit_zero_is_first_of_page_like_space(s):
    typed(s, "a")
    assert s.handle(Key(char="0")).commit == "日"


def test_digit_out_of_range_is_error(s):
    typed(s, "hdi")
    n = len(s.cands)
    r = s.handle(Key(char=str(min(9, n))))  # 候補数ちょうどの番号は存在しない
    if n <= 9:
        assert r.error and r.handled and not r.commit
        assert s.buf == "hdi"  # 何も入力せず、書きかけも残る


def test_space_without_interpretation_is_error_and_inputs_nothing(s):
    typed(s, "aq")
    r = press(s, "space")
    assert r.error and r.handled and r.commit == ""
    assert s.buf == "aq"


def test_error_on_digit_when_uninterpretable(s):
    typed(s, "aq")
    r = s.handle(Key(char="1"))
    assert r.error and r.commit == ""


def test_symbol_commits_first_candidate_then_adds_symbol(s):
    typed(s, "hjhne")
    r = s.handle(Key(char=","))
    assert r.commit == "段、"


def test_symbol_without_interpretation_is_error(s):
    typed(s, "aq")
    r = s.handle(Key(char=","))
    assert r.error and r.commit == ""


def test_symbol_alone_when_empty(s):
    assert s.handle(Key(char=".")).commit == "。"
    assert s.handle(Key(char="!", shift=True)).commit == "！"


def test_space_when_empty_goes_to_app(s):
    r = press(s, "space")
    assert not r.handled and r.commit == ""


def test_unknown_char_when_empty_goes_to_app(s):
    assert not s.handle(Key(char="5")).handled
    assert not s.handle(Key(char="A", shift=True)).handled


def test_backspace_edits_buffer_and_recomputes(s):
    typed(s, "ai")
    assert s.cands[0] == "あい"
    press(s, "BackSpace")
    assert s.buf == "a" and s.cands[0] == "日"
    press(s, "BackSpace")
    assert s.buf == "" and s.cands == []
    assert not press(s, "BackSpace").handled  # 空なら、アプリのBackSpaceに任せる


def test_escape_cancels(s):
    typed(s, "hdi")
    r = press(s, "Escape")
    assert r.handled and r.commit == "" and s.buf == ""


def test_return_commits_typed_keys_as_is(s):
    typed(s, "hello")
    assert press(s, "Return").commit == "hello"


def test_return_when_empty_goes_to_app(s):
    assert not press(s, "Return").handled


def test_arrow_wraps_around(s):
    typed(s, "a")
    n = len(s.cands)
    press(s, "Up")
    assert s.cursor == n - 1
    press(s, "Down")
    assert s.cursor == 0


def test_paging(hepburn_compiled):
    s = make(hepburn_compiled, page_size=2)
    typed(s, "giru")  # ['ぎる', '坮う', '去る', '圹る', '圡る', '土いる']
    assert len(s.cands) == 6
    press(s, "Page_Down")
    assert s.cursor == 2 and s.page_start == 2
    press(s, "Page_Down")
    assert s.page_start == 4
    press(s, "Page_Down")  # 最後のページの次は先頭へ
    assert s.cursor == 0
    press(s, "Page_Up")  # 先頭の前は最後のページへ
    assert s.page_start == 4
    press(s, "Page_Up")
    assert s.page_start == 2


def test_digit_uses_current_page(hepburn_compiled):
    s = make(hepburn_compiled, page_size=2)
    typed(s, "giru")
    expected = s.cands[2 + 1]
    press(s, "Page_Down")
    assert s.handle(Key(char="1")).commit == expected


def test_direct_mode_passes_everything(hepburn_compiled):
    s = make(hepburn_compiled, Mode.DIRECT)
    assert not s.handle(Key(char="a")).handled
    assert not s.handle(Key(char=",")).handled


def test_ctrl_keys_pass_through(s):
    assert not s.handle(Key(char="c", ctrl=True)).handled
    typed(s, "hdi")
    assert not s.handle(Key(char="c", ctrl=True)).handled
    assert s.buf == "hdi"


def test_mode_key_cycles_and_clears(hepburn_compiled):
    s = make(hepburn_compiled)
    typed(s, "hdi")
    r = s.handle(Key(char="M", ctrl=True, shift=True))
    assert r.handled and s.mode is Mode.HANWA_KATA and s.buf == ""
    s.handle(Key(char="M", ctrl=True, shift=True))
    assert s.mode is Mode.DIRECT


def test_hyphen_starts_katakana_word(s):
    typed(s, "-katakana")
    assert s.cands == ["カタカナ"]
    assert press(s, "space").commit == "カタカナ"


def test_preedit_latin_and_map(hepburn_compiled):
    s = make(hepburn_compiled)
    typed(s, "hdi")
    assert s.preedit == "hdi"
    from c01.tables import compile_tables

    s2 = Session(compile_tables(Config(preedit="map")), Config(preedit="map"), Mode.HANWA_HIRA)
    typed(s2, "hdi")
    assert s2.preedit == "竹木戈"


def test_select_index(s):
    typed(s, "a")
    assert s.select_index(1).commit == "あ"
    typed(s, "a")
    assert s.select_index(99).error
