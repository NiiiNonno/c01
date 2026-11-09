from __future__ import annotations

import pytest

from c01.config import Config, ConfigError, load_config
from c01.importer import import_cangjie5_txt
from c01.sections import SectionError, load_sections
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


def test_bundled_tables_have_expected_codes(hepburn_compiled):
    h = hepburn_compiled.heads
    assert h["hdi"][0] == "私"
    assert h["oiar"][0] == "倉"
    assert h["a"][0] == "日"
    assert "々" in h["ko"] and "ヶ" in h["kh"]  # 追加表の分
    assert not any(code.startswith("z") for code in h)  # 特殊コードは除いてある


def test_symbol_keys_overlapping_input_keys_are_dropped(hepburn_compiled):
    # '-' や z など、打鍵に使う文字は記号テーブルに書いても無視される
    assert "," in hepburn_compiled.symbols
    assert "-" not in hepburn_compiled.symbols
    assert "z" in hepburn_compiled.buffer_chars and "-" in hepburn_compiled.buffer_chars


def test_bundled_compound_lists_compile_without_warnings(hepburn_compiled):
    assert hepburn_compiled.warnings == []
    texts = {e[0] for entries in hepburn_compiled.compound.values() for e in entries}
    assert {"倉頡", "去る", "去っ", "真ん中", "ラ行", "その他", "による", "によって"} <= texts


# ---- セクション形式 ------------------------------------------------------

def _sec(tmp_path, body):
    p = tmp_path / "t.txt"
    p.write_text(body, encoding="utf-8")
    return load_sections(p)


def test_section_basic(tmp_path):
    items = _sec(tmp_path, "; 注釈\n[甲]\n日\n木\n[助詞]\nは\nが\n[く]\n()\nか\nき\n"
                 "[!A]\n(甲)(助詞)\n必ず\n[!B]\n咲(く)\n")
    assert [(l, t) for _, l, t in items] == [
        ("A", "日は"), ("A", "日が"), ("A", "木は"), ("A", "木が"), ("A", "必ず"),
        ("B", "咲"), ("B", "咲か"), ("B", "咲き"),
    ]


def test_section_nesting_and_predefined(tmp_path):
    items = _sec(tmp_path, "[a]\nい\n[b]\n(a)\nう\n[!X]\n(OPEN)(b)(CLOSE)\n")
    assert [t for _, _, t in items] == ["(い)", "(う)"]


@pytest.mark.parametrize(
    "body, msg",
    [
        ("[!X]\n(無い)\n", "定義されていません"),  # 未定義
        ("[!X]\n(a)\n[a]\nい\n", "定義されていません"),  # 先に参照
        ("[a]\nい\n[a]\nう\n", "すでに定義"),
        ("[OPEN]\nx\n", "定義済み"),
        ("い\n[a]\n", "より前"),
        ("[!X]\n咲(く\n", "括弧"),
    ],
)
def test_section_errors(tmp_path, body, msg):
    with pytest.raises(SectionError, match=msg):
        _sec(tmp_path, body)


def test_references_do_not_cross_files(tmp_path, monkeypatch):
    monkeypatch.setenv("C01_DATA_DIR", str(tmp_path))
    (tmp_path / "compound").mkdir()
    (tmp_path / "compound/a.txt").write_text("[甲]\n日\n", encoding="utf-8")
    (tmp_path / "compound/b.txt").write_text("[!X]\n(甲)は\n", encoding="utf-8")
    with pytest.raises(TableError, match="定義されていません"):
        compile_tables(Config(compound=["a", "b"]))


def test_bundled_classes_do_not_make_nonexistent_forms(hepburn_compiled):
    texts = {e[0] for entries in hepburn_compiled.compound.values() for e in entries}
    assert {"見る", "見れ", "見ろ"} <= texts
    assert not texts & {"見り", "見っ", "見ら"}  # 一段活用の型には無い形
    assert {"去り", "去っ", "老いる", "悲しい", "日は", "木では", "いらっしゃい"} <= texts


# ---- 字種の絞り込み ------------------------------------------------------

def _mini(tmp_path, monkeypatch, **extra):
    monkeypatch.setenv("C01_DATA_DIR", str(tmp_path))
    write_csv(tmp_path / "head/mini.csv", [("日", "a"), ("倉", "oiar"), ("仓", "oiar")])
    return Config(head=["mini"], compound=[], **extra)


def test_script_filter_with_variants(tmp_path, monkeypatch):
    # 「倉」を繁体字扱い、「仓」を簡体字扱いにしてみる
    write_csv(tmp_path / "variants/t.csv", [("倉", "trad"), ("仓", "simp")])
    cfg = _mini(tmp_path, monkeypatch, variants="t", script="trad")
    c = compile_tables(cfg)
    assert c.heads["oiar"] == ("倉",) and c.heads["a"] == ("日",)
    cfg.script = "simp"
    assert compile_tables(cfg).heads["oiar"] == ("仓",)
    cfg.script = "all"
    assert compile_tables(cfg).heads["oiar"] == ("倉", "仓")


def test_script_filter_also_filters_compound_entries(tmp_path, monkeypatch):
    write_csv(tmp_path / "variants/t.csv", [("倉", "trad"), ("仓", "simp")])
    cfg = _mini(tmp_path, monkeypatch, variants="t", script="simp")
    (tmp_path / "compound").mkdir()
    (tmp_path / "compound/j.txt").write_text("[!x]\n倉日\n仓日\n", encoding="utf-8")
    cfg.compound = ["j"]
    c = compile_tables(cfg)
    assert [e[0] for e in c.compound["oiara"]] == ["仓日"]


def test_script_without_variants_warns_and_keeps_all():
    c = compile_tables(Config(script="trad"))
    assert any("variants" in w for w in c.warnings)
    assert "倉" in c.heads["oiar"]


# ---- コンパイルのキャッシュ ------------------------------------------------

def test_compile_cache_reused_and_invalidated(tmp_path, monkeypatch):
    cfg = _mini(tmp_path, monkeypatch)
    c1 = load_or_compile(cfg)
    assert c1.fingerprint == current_fingerprint(cfg)
    assert load_or_compile(cfg).fingerprint == c1.fingerprint
    write_csv(tmp_path / "head/mini.csv", [("日", "a"), ("月", "b")])  # サイズが変わる
    assert current_fingerprint(cfg) != c1.fingerprint
    assert load_or_compile(cfg).heads["b"] == ("月",)


def test_compound_list_change_invalidates_cache(tmp_path, monkeypatch):
    cfg = _mini(tmp_path, monkeypatch)
    (tmp_path / "compound").mkdir()
    (tmp_path / "compound/j.txt").write_text("倉日\n", encoding="utf-8")
    cfg.compound = ["j"]
    fp = current_fingerprint(cfg)
    (tmp_path / "compound/j.txt").write_text("倉日\n日日\n", encoding="utf-8")
    assert current_fingerprint(cfg) != fp


def test_user_table_overrides_bundled(tmp_path, monkeypatch):
    monkeypatch.setenv("C01_DATA_DIR", str(tmp_path))
    write_csv(tmp_path / "head/custom.csv", [("々", "xyz")])  # 同梱の custom.csv を置き換える
    c = compile_tables(Config())
    assert c.heads["xyz"] == ("々",)
    assert "々" not in c.heads.get("ko", ())  # 同梱の割り当ては使われない


def test_compound_priority_follows_list_order(tmp_path, monkeypatch):
    cfg = _mini(tmp_path, monkeypatch)
    (tmp_path / "compound").mkdir()
    (tmp_path / "compound/x.txt").write_text("[!x]\n倉\n", encoding="utf-8")
    (tmp_path / "compound/y.txt").write_text("[!x]\n仓\n", encoding="utf-8")
    cfg.compound = ["x", "y"]
    assert [e[0] for e in compile_tables(cfg).compound["oiar"]] == ["倉", "仓"]
    cfg.compound = ["y", "x"]
    assert [e[0] for e in compile_tables(cfg).compound["oiar"]] == ["仓", "倉"]


def test_head_priority_follows_list_order(tmp_path, monkeypatch):
    monkeypatch.setenv("C01_DATA_DIR", str(tmp_path))
    write_csv(tmp_path / "head/p.csv", [("日", "a")])
    write_csv(tmp_path / "head/q.csv", [("曰", "a")])
    assert compile_tables(Config(head=["p", "q"], compound=[])).heads["a"] == ("日", "曰")
    assert compile_tables(Config(head=["q", "p"], compound=[])).heads["a"] == ("曰", "日")


def test_unmakeable_entries_warn_and_are_skipped(tmp_path, monkeypatch):
    cfg = _mini(tmp_path, monkeypatch)
    (tmp_path / "compound").mkdir()
    (tmp_path / "compound/j.txt").write_text("[!x]\n日月\n日\n", encoding="utf-8")  # 月 は表に無い
    cfg.compound = ["j"]
    c = compile_tables(cfg)
    assert [e[0] for e in c.compound["a"]] == ["日"]
    assert any("日月" in w for w in c.warnings)


# ---- 設定 --------------------------------------------------------------

def test_config_defaults_when_file_missing():
    cfg = load_config()
    assert cfg.mode == "hanwa" and cfg.tail == "hiragana-hepburn" and cfg.pure == ["katakana-hepburn"]
    assert cfg.head == ["cangjie5", "custom"]
    assert cfg.compound == ["default"]


def test_old_config_keys_are_now_errors(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('romaji = "a"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_config_reads_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('mode = "kanji"\npage_size = 5\nerror_sound = "/x/e.wav"\n', encoding="utf-8")
    cfg = load_config(p)
    assert (cfg.mode, cfg.page_size, cfg.error_sound) == ("kanji", 5, "/x/e.wav")


@pytest.mark.parametrize(
    "body", ['mode = "nope"', 'tail = ""', "head = []", "page_size = 0", 'script = "x"', "zzz = 1", "= broken"]
)
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
