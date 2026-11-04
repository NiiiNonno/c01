"""テスト用の設定。本物の倉頡表（同梱の cangjie5.csv）を使い、仮名表だけ利用者の方式を模したものを用意する。"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from c01.config import Config
from c01.tables import compile_tables

VOWELS = "aiueo"

# 利用者の例文の打鍵に合わせた仮名表: は行が f、し は si、ー は -
USER_ROWS = {
    "": "あいうえお",
    "k": "かきくけこ", "s": "さしすせそ", "t": "たちつてと", "n": "なにぬねの",
    "f": "はひふへほ", "m": "まみむめも", "r": "らりるれろ",
    "g": "がぎぐげご", "z": "ざじずぜぞ", "d": "だぢづでど",
    "b": "ばびぶべぼ", "p": "ぱぴぷぺぽ",
}


def user_hira_rows():
    rows = []
    for cons, kana in USER_ROWS.items():
        for v, k in zip(VOWELS, kana):
            rows.append((cons + v, k, ""))
    rows += [("ya", "や", ""), ("yu", "ゆ", ""), ("yo", "よ", ""), ("wa", "わ", ""), ("wo", "を", "")]
    rows += [("n'", "ん", ""), ("n", "ん", ""), ("-", "ー", "")]
    rows += [("lya", "ゃ", ""), ("lyu", "ゅ", ""), ("lyo", "ょ", ""), ("ltu", "っ", "")]
    rows += [(c + c, "っ", c) for c in "ksptgzdbf"]
    return rows


def user_kata_rows():
    def to_kata(s):
        return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)

    rows = [(k, to_kata(o), n) for k, o, n in user_hira_rows()]
    for pre, base in (("ky", "き"), ("sy", "し"), ("ty", "ち"), ("ny", "に"), ("fy", "ひ"), ("my", "み"), ("ry", "り")):
        for v, small in (("a", "ゃ"), ("u", "ゅ"), ("o", "ょ")):
            rows.append((pre + v, to_kata(base + small), ""))
    return rows


def write_csv(path: Path, rows, header: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        if header:
            f.write(header + "\n")
        csv.writer(f, lineterminator="\n").writerows(rows)


@pytest.fixture(scope="session")
def user_data(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("c01data")
    write_csv(d / "romaji/user/hiragana.csv", user_hira_rows(), "# テスト用")
    write_csv(d / "romaji/user/katakana.csv", user_kata_rows(), "# テスト用")
    # 法(egi)は えぎ とも読めるので、漢字を先に出したいものとして挙げる
    write_csv(d / "priority/user.csv", [("日",), ("山",), ("水",), ("人",), ("法",)], "# テスト用")
    return d


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch, user_data):
    """利用者の設定・キャッシュは空の一時フォルダ。データ置き場だけ上のテスト用表を指す。"""
    monkeypatch.setenv("C01_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("C01_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("C01_DATA_DIR", str(user_data))


@pytest.fixture(scope="session")
def user_cfg() -> Config:
    return Config(romaji="user", mode="hanwa_hira")


def _compile_with_data(cfg: Config, data_dir: Path):
    # session スコープでは autouse の monkeypatch が使えないので、環境変数を直接立てる
    import os

    old = os.environ.get("C01_DATA_DIR")
    os.environ["C01_DATA_DIR"] = str(data_dir)
    try:
        return compile_tables(cfg)
    finally:
        if old is None:
            del os.environ["C01_DATA_DIR"]
        else:
            os.environ["C01_DATA_DIR"] = old


@pytest.fixture(scope="session")
def user_compiled(user_cfg, user_data):
    return _compile_with_data(user_cfg, user_data)


@pytest.fixture(scope="session")
def user_cfg_prio() -> Config:
    return Config(romaji="user", kanji_priority="user", mode="hanwa_hira")


@pytest.fixture(scope="session")
def user_compiled_prio(user_cfg_prio, user_data):
    return _compile_with_data(user_cfg_prio, user_data)


@pytest.fixture(scope="session")
def hepburn_compiled():
    return compile_tables(Config(romaji="hepburn"))
