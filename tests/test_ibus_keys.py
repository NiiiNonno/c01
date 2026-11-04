"""ibus が無くても確かめられる、キーの変換部分。"""

from __future__ import annotations

import pytest

from c01.ibus_engine import translate_key


def k(name, char="", shift=False, ctrl=False, alt=False, sup=False):
    return translate_key(name, char, shift, ctrl, alt, sup)


def test_space_has_char():
    key = k("space", " ")
    assert key.name == "space" and key.char == " "


@pytest.mark.parametrize(
    "ibus_name,expected",
    [("Prior", "Page_Up"), ("Next", "Page_Down"), ("KP_Enter", "Return"), ("KP_Down", "Down"), ("Page_Up", "Page_Up")],
)
def test_aliases(ibus_name, expected):
    key = k(ibus_name, "\r")
    assert key.name == expected and key.char == ""


def test_printable_char():
    key = k("a", "a")
    assert key.name == "" and key.char == "a"
    key = k("comma", ",")
    assert key.char == ","


def test_nonprintable_or_modifier_keys_have_no_char():
    assert k("Shift_L", "\x00").char == ""
    assert k("F5", "").char == "" and k("F5", "").name == ""
    assert k("Return", "\r").char == ""


def test_modifiers_are_carried():
    key = k("m", "M", shift=True, ctrl=True)
    assert key.shift and key.ctrl and not key.alt and not key.super
