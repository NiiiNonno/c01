"""コマンドライン。設定の確認、表のコンパイル、変換の試し打ち、ibus への登録。

  c01 compile            表をコンパイルする（設定やCSVを変えたら実行）
  c01 try [打鍵列...]     変換の候補を確かめる（引数なしなら対話）
  c01 list               選べる表の一覧
  c01 kana [FILE...]     テキストの平仮名を片仮名に変える（-r で逆）
  c01 import-cangjie F   Cangjie5*.txt を C01 の CSV に変換する
  c01 install-ibus       ibus に C01 を登録する
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import time
from pathlib import Path

from .config import (
    ConfigError,
    default_config_path,
    list_choices,
    load_config,
    user_data_dir,
)
from .core import MODE_ORDER, Interpreter, Mode
from .kana import hira_to_kata, kata_to_hira
from .tables import TableError, compile_tables, load_or_compile, save_compiled


def _load(args) -> tuple:
    cfg = load_config(args.config)
    if getattr(args, "mode", None):
        cfg.mode = args.mode
    if getattr(args, "tail", None):
        cfg.tail = args.tail
    cfg.validate()
    return cfg


def cmd_compile(args) -> int:
    cfg = _load(args)
    t = time.perf_counter()
    c = compile_tables(cfg)
    save_compiled(c)
    dt = time.perf_counter() - t
    print(f"コンパイルしました（{dt:.2f}秒）")
    n_head = sum(len(v) for v in c.heads.values())
    n_comp = sum(len(v) for v in c.compound.values())
    print(f"  tail {len(c.tail)} 件 / pure {', '.join(str(len(t)) for t in c.pures) or '-'} 件 / 記号 {len(c.symbols)} 件")
    print(f"  首辞の字 {n_head} 字（{len(c.heads)} コード）/ 複合首辞 {n_comp} 件（{len(c.compound)} 打鍵列）")
    for w in c.warnings:
        print(f"  注意: {w}")
    return 0


def _show(interp: Interpreter, mode: Mode, token: str, limit: int) -> None:
    cands = interp.candidates(token, mode)
    if not cands:
        print(f"{token}\t(解釈できません: スペースでエラー音)")
        return
    shown = "  ".join(f"{i}:{t}" for i, t in enumerate(cands[:limit]))
    more = f"  …他{len(cands) - limit}件" if len(cands) > limit else ""
    print(f"{token}\t{shown}{more}")


def cmd_try(args) -> int:
    cfg = _load(args)
    c = load_or_compile(cfg)
    interp = Interpreter(c, cfg.max_split_kanji)
    mode = Mode(cfg.mode)
    if args.keys:
        for tok in " ".join(args.keys).split():
            _show(interp, mode, tok, args.limit)
        return 0
    print(f"モード: {mode.value}。スペースで区切って打鍵列を入れる。空行で終了")
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        if not line.strip():
            break
        for tok in line.split():
            _show(interp, mode, tok, args.limit)
    return 0


def cmd_list(args) -> int:
    for sub in ("head", "tail", "pure", "compound", "symbols", "preedit", "variants"):
        names = list_choices(sub)
        print(f"{sub}: {', '.join(names) if names else '(なし)'}")
    print(f"利用者の表を置く場所: {user_data_dir()}")
    print(f"設定ファイル: {default_config_path()}")
    return 0


def cmd_kana(args) -> int:
    conv = kata_to_hira if args.reverse else hira_to_kata
    if not args.files:
        if args.in_place:
            print("-i はファイルを指定したときだけ使えます", file=sys.stderr)
            return 2
        sys.stdout.write(conv(sys.stdin.read()))
        return 0
    for name in args.files:
        path = Path(name)
        text = conv(path.read_text(encoding="utf-8"))
        if args.in_place:
            path.write_text(text, encoding="utf-8")
        elif args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    return 0


def cmd_import_cangjie(args) -> int:
    from .importer import import_cangjie5_txt

    dst = Path(args.out) if args.out else user_data_dir() / "head" / f"{args.name}.csv"
    kept, skipped = import_cangjie5_txt(Path(args.src), dst, keep_z=args.keep_z)
    print(f"{dst} に {kept} 行を書きました（{skipped} 行は飛ばしました）")
    return 0


COMPONENT_XML = """<?xml version="1.0" encoding="utf-8"?>
<component>
  <name>org.freedesktop.IBus.C01</name>
  <description>C01: ローマ字の仮名と倉頡で漢字を統一入力</description>
  <exec>{exec_path} --ibus</exec>
  <version>{version}</version>
  <author>C01</author>
  <license>MIT</license>
  <textdomain>c01</textdomain>
  <engines>
    <engine>
      <name>c01</name>
      <language>ja</language>
      <license>MIT</license>
      <author>C01</author>
      <icon>input-keyboard</icon>
      <layout>default</layout>
      <longname>C01</longname>
      <description>ローマ字の仮名と倉頡で漢字を統一入力</description>
      <rank>1</rank>
    </engine>
  </engines>
</component>
"""


def cmd_install_ibus(args) -> int:
    from . import __version__

    root = Path(__file__).resolve().parent.parent
    launcher = root / "ibus" / "c01-engine"
    if not launcher.exists():
        print(f"起動スクリプトが見つかりません: {launcher}", file=sys.stderr)
        return 1
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if not args.user:
        # ibus-daemon が確実に読むのは /usr/share/ibus/component（と IBUS_COMPONENT_PATH）だけ
        comp_dir = Path("/usr/share/ibus/component")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        comp_dir = Path(base) / "ibus" / "component"
    xml = COMPONENT_XML.format(exec_path=str(launcher), version=__version__)
    dst = comp_dir / "c01.xml"
    if args.print_only:
        print(f"# 書き込み先: {dst}")
        print(xml)
        return 0
    try:
        comp_dir.mkdir(parents=True, exist_ok=True)
        dst.write_text(xml, encoding="utf-8")
    except PermissionError:
        print(f"{dst} に書けません。sudo で実行してください（sudo python3 -m c01 install-ibus）", file=sys.stderr)
        return 1
    print(f"{dst} を書きました")
    print("次を実行すると反映されます:")
    print("  c01 compile            # 表のコンパイル（まだなら）")
    print("  ibus write-cache       # 登録の一覧を作り直す")
    print("  ibus restart           # ibus を再起動")
    print("  ibus list-engine | grep c01   # 出れば登録できている")
    print("そのあと 設定 → キーボード → 入力ソース → ＋ → 日本語 の中の C01 を追加してください")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="c01", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help=f"設定ファイル（既定: {default_config_path()}）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("compile", help="表をコンパイルする")
    s.set_defaults(func=cmd_compile)

    s = sub.add_parser("try", help="変換の候補を確かめる")
    s.add_argument("keys", nargs="*", help="打鍵列（スペース区切りで複数）")
    s.add_argument("-m", "--mode", choices=[m.value for m in MODE_ORDER], help="モード（既定は設定のもの）")
    s.add_argument("-t", "--tail", help="尾辞の表の名前（例: katakana-hepburn。既定は設定のもの）")
    s.add_argument("-n", "--limit", type=int, default=12, help="表示する候補の最大数")
    s.set_defaults(func=cmd_try)

    s = sub.add_parser("list", help="選べる表の一覧")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("kana", help="テキストの平仮名を片仮名に変える（標準入力→標準出力）")
    s.add_argument("files", nargs="*", help="ファイル（省略すると標準入力）")
    s.add_argument("-r", "--reverse", action="store_true", help="片仮名を平仮名に変える")
    s.add_argument("-i", "--in-place", action="store_true", help="ファイルを書き換える")
    s.add_argument("-o", "--output", help="出力先のファイル（ファイルが1つのとき）")
    s.set_defaults(func=cmd_kana)

    s = sub.add_parser("import-cangjie", help="Cangjie5*.txt をCSVに変換する")
    s.add_argument("src", help="Cangjie5.txt のパス")
    s.add_argument("--name", default="cangjie5", help="利用者の表の名前（既定: cangjie5）。data/head/<名前>.csv に出る")
    s.add_argument("--out", help="出力先を直接指定する")
    s.add_argument("--keep-z", action="store_true", help="z で始まる特殊コードも残す")
    s.set_defaults(func=cmd_import_cangjie)

    s = sub.add_parser("install-ibus", help="ibus に登録する")
    s.add_argument("--user", action="store_true", help="~/.local/share/ibus/component に入れる（ibus が読まない場合が多い）")
    s.add_argument("--print-only", action="store_true", help="書かずに内容だけ表示する")
    s.set_defaults(func=cmd_install_ibus)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, TableError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
