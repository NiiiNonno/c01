from __future__ import annotations

import pytest

from c01.cli import main
from c01.kana import has_kana, hira_to_kata, kata_to_hira, script_of


def test_hira_to_kata():
    assert hira_to_kata("ひらがなをカタカナに。漢字はそのまま、ゔ・ゝゞ") == "ヒラガナヲカタカナニ。漢字ハソノママ、ヴ・ヽヾ"
    assert hira_to_kata("る*") == "ル*"  # ワイルドカードの記号は変えない
    assert hira_to_kata("ー") == "ー"


def test_kata_to_hira():
    assert kata_to_hira("カタカナ、ヴ、ヽヾ、ー") == "かたかな、ゔ、ゝゞ、ー"


def test_round_trip_for_every_kana():
    hira = "".join(chr(o) for o in range(0x3041, 0x3097))
    assert kata_to_hira(hira_to_kata(hira)) == hira


def test_script_of():
    assert script_of("あ") == "h" and script_of("ア") == "k" and script_of("ー") == "k"
    assert script_of("𛄟") == "h"
    assert script_of("漢") == "" and script_of("a") == ""
    assert has_kana("去る") and not has_kana("倉頡")


def test_cli_kana_stdout_and_in_place(tmp_path, capsys):
    f = tmp_path / "list.txt"
    f.write_text("去る*\nそれ\n", encoding="utf-8")
    assert main(["kana", str(f)]) == 0
    assert capsys.readouterr().out == "去ル*\nソレ\n"
    assert f.read_text(encoding="utf-8") == "去る*\nそれ\n"  # 元は変えない
    assert main(["kana", "-i", str(f)]) == 0
    assert f.read_text(encoding="utf-8") == "去ル*\nソレ\n"
    assert main(["kana", "-r", "-i", str(f)]) == 0
    assert f.read_text(encoding="utf-8") == "去る*\nそれ\n"


def test_cli_kana_output_file(tmp_path):
    f, g = tmp_path / "a.txt", tmp_path / "b.txt"
    f.write_text("かな", encoding="utf-8")
    assert main(["kana", "-o", str(g), str(f)]) == 0
    assert g.read_text(encoding="utf-8") == "カナ"


def test_cli_kana_stdin(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("かな\n"))
    assert main(["kana"]) == 0
    assert capsys.readouterr().out == "カナ\n"


def test_cli_try_and_compile(capsys):
    assert main(["compile"]) == 0
    assert "複合首辞" in capsys.readouterr().out
    assert main(["try", "--", "giru"]) == 0
    assert "0:去る" in capsys.readouterr().out
    assert main(["try", "-t", "katakana", "--", "giu"]) == 0
    assert "去ウ" in capsys.readouterr().out
