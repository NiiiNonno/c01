"""同梱のサンプルテーブル（ヘボン式の仮名、記号、置き換え表など）を作る。

利用者は自分の表を ~/.local/share/c01/ の下に置けば、同梱のものより優先される。
"""

from __future__ import annotations

import csv
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "c01" / "data"

# ---- 仮名 -------------------------------------------------------------
VOWELS = [("a", "あ"), ("i", "い"), ("u", "う"), ("e", "え"), ("o", "お")]

# (ローマ字の子音部, [あ行, い, う, え, お に当たる仮名]) ヘボン式
ROWS = [
    ("k", "かきくけこ"), ("s", None), ("t", None), ("n", "なにぬねの"), ("h", None),
    ("m", "まみむめも"), ("r", "らりるれろ"),
    ("g", "がぎぐげご"), ("z", "ざじずぜぞ"), ("d", "だぢづでど"),
    ("b", "ばびぶべぼ"), ("p", "ぱぴぷぺぽ"),
]

HIRA: list[tuple[str, str, str]] = []  # (入力, 出力, 残す入力)


def add(table, key, out, nxt=""):
    table.append((key, out, nxt))


def base_gojuon(table):
    for k, v in VOWELS:
        add(table, k, v)
    for cons, kana in (
        ("k", "かきくけこ"), ("n", "なにぬねの"), ("m", "まみむめも"), ("r", "らりるれろ"),
        ("g", "がぎぐげご"), ("b", "ばびぶべぼ"), ("p", "ぱぴぷぺぽ"),
    ):
        for (v, _), ch in zip(VOWELS, kana):
            add(table, cons + v, ch)
    # ヘボン式の特別な綴り
    for key, out in (
        ("sa", "さ"), ("shi", "し"), ("su", "す"), ("se", "せ"), ("so", "そ"),
        ("ta", "た"), ("chi", "ち"), ("tsu", "つ"), ("te", "て"), ("to", "と"),
        ("ha", "は"), ("hi", "ひ"), ("fu", "ふ"), ("he", "へ"), ("ho", "ほ"),
        ("ya", "や"), ("yu", "ゆ"), ("yo", "よ"),
        ("wa", "わ"), ("wo", "を"),
        ("ja", "じゃ"[0:0] or "ざ"),  # 置き換えるので下で上書き（ここは使わない）
    ):
        add(table, key, out)
    # ざ行・だ行（ヘボン式: ji, zu で じ/ず。ぢ/づ は di/du）
    for key, out in (
        ("za", "ざ"), ("ji", "じ"), ("zu", "ず"), ("ze", "ぜ"), ("zo", "ぞ"),
        ("da", "だ"), ("di", "ぢ"), ("du", "づ"), ("de", "で"), ("do", "ど"),
    ):
        add(table, key, out)
    add(table, "n'", "ん")
    add(table, "n", "ん")  # 「nn」は入れない: onna → おんな と読めるように
    add(table, "-", "ー")


def small_kana(table):
    for key, out in (
        ("la", "ぁ"), ("li", "ぃ"), ("lu", "ぅ"), ("le", "ぇ"), ("lo", "ぉ"),
        ("xa", "ぁ"), ("xi", "ぃ"), ("xu", "ぅ"), ("xe", "ぇ"), ("xo", "ぉ"),
        ("lya", "ゃ"), ("lyu", "ゅ"), ("lyo", "ょ"), ("xya", "ゃ"), ("xyu", "ゅ"), ("xyo", "ょ"),
        ("lwa", "ゎ"), ("xwa", "ゎ"), ("ltu", "っ"), ("xtu", "っ"), ("ltsu", "っ"), ("xtsu", "っ"),
    ):
        add(table, key, out)


def sokuon(table):
    for c in "kstpgzdbjf":
        add(table, c + c, "っ", c)
    add(table, "tc", "っ", "c")  # matcha → まっちゃ のように tch を読む


def make_hira():
    t: list[tuple[str, str, str]] = []
    base_gojuon(t)
    # 上で入れた ja の仮置きを消す
    t = [r for r in t if r[0] != "ja"]
    small_kana(t)
    sokuon(t)
    return t


def make_kata_base():
    """片仮名用: 平仮名用と同じ内容（出力は後で片仮名に変える）＋拗音など。"""
    t = make_hira()
    youon = []
    for pre, base in (
        ("ky", "き"), ("gy", "ぎ"), ("ny", "に"), ("hy", "ひ"), ("by", "び"), ("py", "ぴ"),
        ("my", "み"), ("ry", "り"),
    ):
        for v, small in (("a", "ゃ"), ("u", "ゅ"), ("o", "ょ")):
            youon.append((pre + v, base + small, ""))
    for pre, base in (("sh", "し"), ("ch", "ち"), ("j", "じ")):
        for v, small in (("a", "ゃ"), ("u", "ゅ"), ("o", "ょ")):
            youon.append((pre + v, base + small, ""))
    youon += [("she", "しぇ", ""), ("che", "ちぇ", ""), ("je", "じぇ", "")]
    # 外来音
    youon += [
        ("fa", "ふぁ", ""), ("fi", "ふぃ", ""), ("fe", "ふぇ", ""), ("fo", "ふぉ", ""),
        ("thi", "てぃ", ""), ("dhi", "でぃ", ""), ("tsa", "つぁ", ""),
        ("wi", "うぃ", ""), ("we", "うぇ", ""),
    ]
    t += youon
    # 拗音の前の促音（kkya など）
    for c in "kstpgzdbjf":
        pass  # c+c は上の sokuon() で「っ + 残り c」として登録済み
    return t


def to_kata(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 0x3041 <= o <= 0x3096:
            out.append(chr(o + 0x60))
        else:
            out.append(ch)
    return "".join(out)


def write_csv(path: Path, header: str, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(header.rstrip("\n") + "\n")
        w = csv.writer(f, lineterminator="\n")
        for r in rows:
            w.writerow(r)


def main():
    hira = make_hira()
    write_csv(
        DATA / "romaji/hepburn/hiragana.csv",
        "# 平仮名用（ヘボン式）。入力,出力,出力後に残す入力\n"
        "# 拗音は lya などでのみ入力。kya などは片仮名用にだけある\n"
        "# 同じ入力が複数あれば後の行が優先",
        hira,
    )
    kata = [(k, to_kata(o), n) for k, o, n in make_kata_base()]
    # 促音の残りは入力側なのでそのまま。出力の「っ」は「ッ」になる
    write_csv(
        DATA / "romaji/hepburn/katakana.csv",
        "# 片仮名用（ヘボン式）。入力,出力,出力後に残す入力\n"
        "# 平仮名用に加えて、拗音（kya など）と外来音を含む",
        kata,
    )

    write_csv(
        DATA / "symbols/default.csv",
        "# 記号キー,出力。仮名・倉頡の入力に使われるキーは書いても無視される",
        [
            (",", "、"), (".", "。"), ("!", "！"), ("?", "？"), ("/", "・"), ("~", "〜"),
            ("[", "「"), ("]", "」"), ("(", "（"), (")", "）"), (":", "："), (";", "；"),
        ],
    )
    write_csv(
        DATA / "symbols/ascii.csv",
        "# 記号キーをそのまま半角で入れる（空の表）。キー,出力",
        [],
    )
    write_csv(
        DATA / "priority/default.csv",
        "# 仮名より先に出す漢字（1行に1つ）。単独で仮名にしにくい a u e o に対応する漢字",
        [("日",), ("山",), ("水",), ("人",)],
    )
    h2k = [(chr(o), chr(o + 0x60)) for o in range(0x3041, 0x3097)] + [("ゝ", "ヽ"), ("ゞ", "ヾ")]
    write_csv(
        DATA / "hira2kata/default.csv",
        "# 和漢混淆（片）で、平仮名を片仮名に置き換える表。平仮名,片仮名",
        h2k,
    )
    radicals = dict(zip("abcdefghijklmnopqrstuvwxy", "日月金木水火土竹戈十大中一弓人心手口尸廿山女田難卜"))
    write_csv(
        DATA / "preedit/cangjie5.csv",
        "# 入力中の表示を倉頡の部首にする表（preedit = \"map\" のとき）。キー,表示",
        [(k, v) for k, v in radicals.items()],
    )
    (DATA / "variants").mkdir(parents=True, exist_ok=True)
    (DATA / "variants/README.txt").write_text(
        "# 文字の分類表（variants/<名前>.csv）を置く場所。\n"
        "# 文字,分類（common/trad/simp/shin）。書いていない文字は common 扱い\n",
        encoding="utf-8",
    )
    print("sample tables written")


if __name__ == "__main__":
    main()
