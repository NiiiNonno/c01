from __future__ import annotations

import pytest

from c01.config import Config, ConfigError, load_config
from c01.importer import import_cangjie5_txt
from c01.tables import (
    TableError,
    compile_tables,
    current_fingerprint,
    load_cangjie,
    load_or_compile,
    load_romaji,
)
from conftest import write_csv


# ---- romaji ------------------------------------------------------------

def test_romaji_three_columns_and_comments(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("# コメント\n\nka,か\nkk,っ,k\n", encoding="utf-8")
    t = load_romaji(p)
    assert t == {"ka": ("か", ""), "kk": ("っ", "k")}


def test_romaji_rejects_remainder_not_shorter(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("k,っ,k\n", encoding="utf-8")
    with pytest.raises(TableError):
        load_romaji(p)


def test_romaji_later_row_wins(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("ka,か\nka,カ\n", encoding="utf-8")
    assert load_romaji(p)["ka"][0] == "カ"


# ---- 倉頡 --------------------------------------------------------------

def test_cangjie_order_dedupe_and_first(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("日,a\n曰,a\n日,a\n", encoding="utf-8")
    b.write_text("甲,a,first\n乙,a\n", encoding="utf-8")
    t = load_cangjie([a, b])
    assert t["a"] == ["甲", "日", "曰", "乙"]


def test_bundled_cangjie_has_expected_codes(hepburn_compiled):
    cj = hepburn_compiled.cangjie
    assert cj["hdi"][0] == "私"
    assert cj["oiar"][0] == "倉"
    assert cj["a"][0] == "日"
    assert "々" in cj["ko"] and "ヶ" in cj["kh"]  # 追加表の分
    assert not any(code.startswith("z") for code in cj)  # 特殊コードは除いてある


def test_symbol_keys_overlapping_input_keys_are_dropped(hepburn_compiled):
    # '-' や ' など、打鍵に使う文字は記号テーブルに書いても無視される
    assert "," in hepburn_compiled.symbols
    assert "-" not in hepburn_compiled.symbols


# ---- 字種の絞り込み ------------------------------------------------------

def test_script_filter_with_variants(tmp_path, monkeypatch):
    monkeypatch.setenv("C01_DATA_DIR", str(tmp_path))
    # 日・曰 は共通、「倉」を繁体字扱いにしてみる
    write_csv(tmp_path / "variants/t.csv", [("倉", "trad"), ("仓", "simp")])
    write_csv(tmp_path / "cangjie/mini.csv", [("日", "a"), ("倉", "oiar"), ("仓", "oiar")])
    cfg = Config(cangjie="mini", cangjie_extra=[], variants="t", script="trad")
    c = compile_tables(cfg)
    assert c.cangjie["oiar"] == ("倉",)
    assert c.cangjie["a"] == ("日",)
    cfg.script = "simp"
    assert compile_tables(cfg).cangjie["oiar"] == ("仓",)
    cfg.script = "all"
    assert compile_tables(cfg).cangjie["oiar"] == ("倉", "仓")


def test_script_without_variants_warns_and_keeps_all():
    c = compile_tables(Config(script="trad"))
    assert any("variants" in w for w in c.warnings)
    assert "倉" in c.cangjie["oiar"]


# ---- コンパイルのキャッシュ ------------------------------------------------

def test_compile_cache_reused_and_invalidated(tmp_path, monkeypatch):
    monkeypatch.setenv("C01_DATA_DIR", str(tmp_path))
    write_csv(tmp_path / "cangjie/mini.csv", [("日", "a")])
    cfg = Config(cangjie="mini", cangjie_extra=[])
    c1 = load_or_compile(cfg)
    assert c1.fingerprint == current_fingerprint(cfg)
    assert load_or_compile(cfg).fingerprint == c1.fingerprint
    write_csv(tmp_path / "cangjie/mini.csv", [("日", "a"), ("月", "b")])  # サイズが変わる
    assert current_fingerprint(cfg) != c1.fingerprint
    assert load_or_compile(cfg).cangjie["b"] == ("月",)


def test_user_table_overrides_bundled(tmp_path, monkeypatch):
    monkeypatch.setenv("C01_DATA_DIR", str(tmp_path))
    write_csv(tmp_path / "cangjie/custom.csv", [("々", "xyz")])  # 同梱の custom.csv を置き換える
    c = compile_tables(Config())
    assert "々" in c.cangjie["xyz"]
    assert "々" not in c.cangjie.get("ko", ())  # 同梱の割り当ては使われない


# ---- 設定 --------------------------------------------------------------

def test_config_defaults_when_file_missing():
    cfg = load_config()
    assert cfg.mode == "hanwa_hira" and cfg.romaji == "hepburn"


def test_config_reads_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('mode = "kanji"\npage_size = 5\nerror_sound = "/x/e.wav"\n', encoding="utf-8")
    cfg = load_config(p)
    assert (cfg.mode, cfg.page_size, cfg.error_sound) == ("kanji", 5, "/x/e.wav")


@pytest.mark.parametrize("body", ['mode = "nope"', "page_size = 0", 'script = "x"', "zzz = 1", "= broken"])
def test_config_rejects_bad_values(tmp_path, body):
    p = tmp_path / "c.toml"
    p.write_text(body + "\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


# ---- 取り込み ------------------------------------------------------------

def test_import_cangjie5_txt(tmp_path):
    src = tmp_path / "Cangjie5.txt"
    src.write_text(
        "標註：\n漢字\t倉頡碼\t標註\n------\n日\ta\n曰\ta\n〇\tzxab\n倉\toiar\t[O]\n\n",
        encoding="utf-8",
    )
    dst = tmp_path / "out" / "c.csv"
    kept, skipped = import_cangjie5_txt(src, dst)
    assert kept == 3 and skipped >= 1
    t = load_cangjie([dst])
    assert t == {"a": ["日", "曰"], "oiar": ["倉"]}
    kept_z, _ = import_cangjie5_txt(src, tmp_path / "z.csv", keep_z=True)
    assert kept_z == 4
