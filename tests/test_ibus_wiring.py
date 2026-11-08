"""偽の IBus を差し込んで、エンジンの配線（キー → Session → 画面への反映）を確かめる。

本物の ibus の API が合っているかは、このテストでは分からない（実機での確認が要る）。
ここで確かめるのは、こちらが書いた部分の誤り（名前の打ち間違い、呼び出し順、状態の反映）。
"""

from __future__ import annotations

import sys
import types

import pytest

KEYVALS = {"space": 0x20, "Return": 0xFF0D, "BackSpace": 0xFF08, "Escape": 0xFF1B, "Up": 0xFF52, "Down": 0xFF54, "Prior": 0xFF55}
NAMES = {v: k for k, v in KEYVALS.items()}


class FakeText:
    def __init__(self, s):
        self.s, self.attrs = s, []

    @classmethod
    def new_from_string(cls, s):
        return cls(s)

    def append_attribute(self, *a):
        self.attrs.append(a)


class FakeTable:
    def __init__(self, page_size):
        self.page_size, self.cands, self.cursor, self.labels = page_size, [], 0, {}

    @classmethod
    def new(cls, page_size, cursor_pos, cursor_visible, round_):
        return cls(page_size)

    def set_label(self, i, t):
        self.labels[i] = t.s

    def append_candidate(self, t):
        self.cands.append(t.s)

    def set_cursor_pos(self, n):
        self.cursor = n


class FakeEngine:
    def __init__(self, connection=None, object_path=None):
        self.object_path = object_path
        self.committed, self.preedit, self.aux, self.table = [], None, None, None
        self.lookup_visible = False

    def commit_text(self, t): self.committed.append(t.s)
    def update_preedit_text(self, t, pos, vis): self.preedit = (t.s, vis)
    def hide_preedit_text(self): self.preedit = None
    def update_auxiliary_text(self, t, vis): self.aux = (t.s, vis)
    def hide_auxiliary_text(self): self.aux = None
    def update_lookup_table(self, table, vis): self.table, self.lookup_visible = table, vis
    def hide_lookup_table(self): self.table, self.lookup_visible = None, False
    def register_properties(self, props): self.registered = props
    def update_property(self, prop): self.updated = prop


class FakeFactory:
    created = []

    def __init__(self, connection=None, object_path=None):
        FakeFactory.created.append(self)


class FakeProp:
    def __init__(self, **kw):
        self.kw = kw

    def set_label(self, t):
        self.kw["label"] = t


class FakeBus:
    def get_connection(self): return object()
    def is_connected(self): return True
    def connect(self, *a): pass
    def request_name(self, *a): self.named = a


class FakeLoop:
    def run(self): pass
    def quit(self): pass


def make_fake_ibus():
    ibus = types.SimpleNamespace(
        Engine=FakeEngine, Factory=FakeFactory, Text=FakeText, LookupTable=FakeTable, Property=FakeProp,
        PropList=lambda: [], Bus=FakeBus, PATH_FACTORY="/f",
        PropType=types.SimpleNamespace(NORMAL=0), PropState=types.SimpleNamespace(UNCHECKED=0),
        AttrType=types.SimpleNamespace(UNDERLINE=1), AttrUnderline=types.SimpleNamespace(SINGLE=1),
        ModifierType=types.SimpleNamespace(
            SHIFT_MASK=1, CONTROL_MASK=4, MOD1_MASK=8, SUPER_MASK=1 << 26, MOD4_MASK=1 << 6, RELEASE_MASK=1 << 30
        ),
        init=lambda: None,
        keyval_name=lambda v: NAMES.get(v, chr(v) if 32 < v < 127 else "Other"),
        keyval_to_unicode=lambda v: chr(v) if 32 <= v < 127 else "\x00",
    )
    return ibus


@pytest.fixture
def engine(monkeypatch):
    ibus = make_fake_ibus()
    gi = types.ModuleType("gi")
    gi.require_version = lambda *a: None
    repo = types.ModuleType("gi.repository")
    repo.IBus = ibus
    repo.GLib = types.SimpleNamespace(MainLoop=FakeLoop)
    repo.GObject = types.SimpleNamespace()
    gi.repository = repo
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repo)
    FakeFactory.created.clear()

    from c01 import ibus_engine

    assert ibus_engine.main(["--ibus"]) == 0
    factory = FakeFactory.created[0]
    assert factory.do_create_engine("other") is None
    eng = factory.do_create_engine("c01")
    eng.do_focus_in()
    return eng


def press(eng, key, state=0):
    v = KEYVALS.get(key, ord(key) if len(key) == 1 else 0)
    return eng.do_process_key_event(v, 0, state)


def type_keys(eng, keys):
    for ch in keys:
        press(eng, "space" if ch == " " else ch)


def test_typing_shows_preedit_and_candidates(engine):
    type_keys(engine, "ai")
    assert engine.preedit == ("ai", True)
    assert engine.table.cands[:2] == ["旷", "𮲜"]
    assert engine.table.cands[-2:] == ["あい", "アイ"]  # 空首辞（尾辞だけ）、pure の順に最下位
    assert engine.table.labels[0] == "0" and engine.lookup_visible
    assert engine.aux[1] is True and engine.aux[0].startswith("[和]")


def test_space_commits_and_clears(engine):
    type_keys(engine, "hdi ")
    assert engine.committed == ["私"]
    assert engine.preedit is None and engine.table is None


def test_down_arrow_moves_cursor_then_space(engine):
    type_keys(engine, "ni")
    assert engine.table.cands[:2] == ["に", "夕"]
    press(engine, "Down")
    assert engine.table.cursor == 1
    press(engine, "space")
    assert engine.committed == ["夕"]


def test_x11_alias_for_page_up_is_consumed_while_composing(engine):
    type_keys(engine, "giru")
    assert press(engine, "Prior") is True  # Page_Up の別名でもキーを食べる
    assert engine.preedit == ("giru", True) and engine.committed == []


def test_unreadable_input_plays_error_and_commits_nothing(engine, monkeypatch):
    played = []
    from c01 import sound

    monkeypatch.setattr(sound, "play", lambda path: played.append(path))
    type_keys(engine, "aq")
    assert press(engine, "space") is True  # キーは食べる
    assert engine.committed == [] and played == [""]
    assert engine.preedit == ("aq", True)


def test_symbol_key_commits_with_symbol(engine):
    type_keys(engine, "hjhne")
    press(engine, ",")
    assert engine.committed == ["段、"]


def test_key_release_is_ignored(engine):
    assert press(engine, "a", state=1 << 30) is False
    assert engine.preedit is None


def test_unhandled_when_empty(engine):
    assert press(engine, "space") is False
    assert press(engine, "Return") is False


def test_focus_out_drops_unfinished_input(engine):
    type_keys(engine, "hdi")
    engine.do_focus_out()
    assert engine.preedit is None and engine.table is None


def test_candidate_click_commits_by_page_position(engine):
    type_keys(engine, "ni")
    engine.do_candidate_clicked(1, 1, 0)
    assert engine.committed == ["夕"]


def test_mode_property_cycles_mode(engine):
    from c01.core import MODE_LABELS, Mode

    engine.do_property_activate("mode", 0)  # 和漢混淆 → 直接入力
    assert press(engine, "a") is False  # 直接入力ではキーをアプリに返す
    engine.do_property_activate("mode", 0)  # → 漢字のみ
    type_keys(engine, "giru")
    assert engine.aux[0].startswith(f"[{MODE_LABELS[Mode.KANJI]}]")
    assert engine.table is None  # 漢字のみでは 去る（仮名を含む）は出ない


def test_z_selects_kana_in_engine(engine):
    type_keys(engine, "kanaz")
    assert engine.table.cands == ["かな", "カナ"]
    press(engine, "space")
    assert engine.committed == ["かな"]


def test_exception_does_not_stop_typing(engine, monkeypatch):
    def boom(key):
        raise RuntimeError("x")

    type_keys(engine, "hd")
    monkeypatch.setattr(engine._session, "handle", boom)
    assert press(engine, "i") is False  # 例外のときはキーをアプリに返す
    assert engine.preedit is None  # 書きかけは捨てて、状態を壊さない
