"""ibus エンジン。キーを Session に渡し、結果を画面（下線つきの入力中の文字・候補窓）に出すだけの薄い層。

判断は全部 session.py / core.py にあり、そちらは ibus なしでテストできる。
このファイルだけは実際の ibus が無いと動かない。

起動: ibus-daemon が component の <exec> から `c01-engine --ibus` を起動する。
手で試す: `ibus/c01-engine`（--ibus なし）。コンポーネントを自分で登録して動く。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from . import __version__, sound
from .config import Config, ConfigError, cache_dir, default_config_path, load_config
from .core import MODE_LABELS, MODE_ORDER, Mode
from .session import Key, Result, Session
from .tables import Compiled, current_fingerprint, load_or_compile

log = logging.getLogger("c01")

BUS_NAME = "org.freedesktop.IBus.C01"
ENGINE_NAME = "c01"

# ibus のキー名のうち、名前の揺れ（X11 の別名）を Session が使う名前にそろえる
KEYNAME_ALIASES = {
    "Prior": "Page_Up",
    "Next": "Page_Down",
    "KP_Enter": "Return",
    "KP_Up": "Up",
    "KP_Down": "Down",
    "KP_Left": "Left",
    "KP_Right": "Right",
    "KP_Page_Up": "Page_Up",
    "KP_Prior": "Page_Up",
    "KP_Page_Down": "Page_Down",
    "KP_Next": "Page_Down",
    "ISO_Left_Tab": "Tab",
    "KP_Home": "Home",
    "KP_End": "End",
    "KP_Delete": "Delete",
}
SESSION_KEYNAMES = {
    "space", "BackSpace", "Return", "Escape", "Tab",
    "Up", "Down", "Left", "Right", "Page_Up", "Page_Down", "Home", "End", "Delete",
}


def translate_key(keyname: str, char: str, shift: bool, ctrl: bool, alt: bool, sup: bool) -> Key:
    """ibus のキー（名前・文字・修飾キー）を Session 用の Key に直す。ibus なしでテストできる。"""
    name = KEYNAME_ALIASES.get(keyname, keyname)
    if name not in SESSION_KEYNAMES:
        name = ""
    if name == "space":
        char = " "
    elif name:
        char = ""  # 名前つきキーは文字を持たない（Return が '\r' になるのを防ぐ）
    elif not (len(char) == 1 and char.isprintable()):
        char = ""
    return Key(name=name, char=char, ctrl=ctrl, alt=alt, shift=shift, super=sup)


class Shared:
    """設定とコンパイル済みの表。全部のエンジンで共有し、変わっていれば読み直す。"""

    def __init__(self) -> None:
        self.config_path = default_config_path()
        self.cfg: Config = Config()
        self.compiled: Compiled | None = None
        self.mode = Mode.HANWA
        self._cfg_mtime = None
        self.error: str = ""
        self.refresh(force=True)

    def _mtime(self):
        try:
            return self.config_path.stat().st_mtime_ns
        except OSError:
            return None

    def refresh(self, force: bool = False) -> bool:
        """変わっていれば読み直す。読み直したら True。失敗したら前のものを使い続ける。"""
        try:
            m = self._mtime()
            changed = force or m != self._cfg_mtime
            cfg = self.cfg
            if changed:
                cfg = load_config(self.config_path)
            fp = current_fingerprint(cfg)
            if not changed and self.compiled is not None and fp == self.compiled.fingerprint:
                return False
            compiled = load_or_compile(cfg)
            for w in compiled.warnings:
                log.warning("表: %s", w)
            first = self.compiled is None
            self.cfg, self.compiled, self._cfg_mtime = cfg, compiled, m
            if first:
                self.mode = Mode(cfg.mode)
            self.error = ""
            return True
        except (ConfigError, OSError, Exception) as e:  # noqa: BLE001 - 入力が止まるよりは前の設定で続ける
            self.error = str(e)
            log.error("設定・表の読み込みに失敗: %s", e)
            if self.compiled is None:
                raise
            return False


def _setup_logging() -> None:
    try:
        d = cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(d / "engine.log"),
            level=os.environ.get("C01_LOG", "INFO").upper(),
            format="%(asctime)s %(levelname)s %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _setup_logging()

    try:
        import gi

        gi.require_version("IBus", "1.0")
        from gi.repository import GLib, GObject, IBus
    except (ImportError, ValueError) as e:
        print(
            "IBus の Python バインディングが見つかりません。次を入れてください:\n"
            "  sudo apt install ibus python3-gi gir1.2-ibus-1.0\n"
            f"（{e}）",
            file=sys.stderr,
        )
        return 1

    IBus.init()
    shared = Shared()

    # ---- ibus 側の定数を、Session のキー名に結びつける --------------------
    MOD = IBus.ModifierType
    mask_shift = int(MOD.SHIFT_MASK)
    mask_ctrl = int(MOD.CONTROL_MASK)
    mask_alt = int(MOD.MOD1_MASK)
    mask_super = int(MOD.SUPER_MASK) | int(MOD.MOD4_MASK)
    mask_release = int(MOD.RELEASE_MASK)

    class C01Engine(IBus.Engine):
        __gtype_name__ = "EngineC01"

        def __init__(self, bus, object_path):
            super().__init__(connection=bus.get_connection(), object_path=object_path)
            self._session = Session(shared.compiled, shared.cfg, shared.mode)
            self._props = None
            self._make_properties()

        # --- 設定の読み直し -------------------------------------------
        def _sync(self) -> None:
            if shared.refresh():
                self._session = Session(shared.compiled, shared.cfg, shared.mode)
                log.info("設定・表を読み直しました")
            else:
                self._session.mode = shared.mode

        # --- 画面 -----------------------------------------------------
        def _text(self, s: str):
            return IBus.Text.new_from_string(s)

        def _make_properties(self) -> None:
            try:
                self._props = IBus.PropList()
                self._mode_prop = IBus.Property(
                    key="mode",
                    prop_type=IBus.PropType.NORMAL,
                    label=self._text(self._mode_label()),
                    icon="",
                    tooltip=self._text("入力モード（押すと切り替え）"),
                    sensitive=True,
                    visible=True,
                    state=IBus.PropState.UNCHECKED,
                    sub_props=None,
                )
                self._props.append(self._mode_prop)
            except Exception:  # noqa: BLE001 - 無くても入力はできる
                log.exception("プロパティの作成に失敗")
                self._props = None

        def _mode_label(self) -> str:
            return MODE_LABELS[self._session.mode]

        def _update_mode_prop(self) -> None:
            if self._props is None:
                return
            try:
                self._mode_prop.set_label(self._text(self._mode_label()))
                self.update_property(self._mode_prop)
            except Exception:  # noqa: BLE001
                log.exception("プロパティの更新に失敗")

        def _refresh(self) -> None:
            s = self._session
            if not s.buf:
                self.hide_preedit_text()
                self.hide_auxiliary_text()
                self.hide_lookup_table()
                return

            pre = s.preedit
            t = self._text(pre)
            t.append_attribute(IBus.AttrType.UNDERLINE, IBus.AttrUnderline.SINGLE, 0, len(pre))
            self.update_preedit_text(t, len(pre), True)

            self.update_auxiliary_text(self._text(f"[{self._mode_label()}] {len(s.cands)}件"), bool(s.cands))
            if not s.cands:
                self.hide_lookup_table()
                return
            table = IBus.LookupTable.new(s.page_size, 0, True, True)
            for i in range(s.page_size):
                table.set_label(i, self._text(str(i)))
            for c in s.cands:
                table.append_candidate(self._text(c))
            table.set_cursor_pos(s.cursor)
            self.update_lookup_table(table, True)

        def _apply(self, r: Result) -> bool:
            if r.commit:
                self.commit_text(self._text(r.commit))
            if r.error:
                sound.play(self._session.cfg.error_sound)
            self._refresh()
            return r.handled

        # --- ibus からの呼び出し ---------------------------------------
        def do_process_key_event(self, keyval, keycode, state):
            try:
                if state & mask_release:
                    return False
                s = self._session
                mode_before = s.mode
                name = IBus.keyval_name(keyval) or ""
                u = IBus.keyval_to_unicode(keyval)
                key = translate_key(
                    name,
                    u if isinstance(u, str) else "",
                    bool(state & mask_shift),
                    bool(state & mask_ctrl),
                    bool(state & mask_alt),
                    bool(state & mask_super),
                )
                r = s.handle(key)
                if s.mode is not mode_before:
                    shared.mode = s.mode
                    self._update_mode_prop()
                return self._apply(r)
            except Exception:  # noqa: BLE001 - 例外でキー入力が止まらないように
                log.exception("キー処理で例外")
                self._session.reset()
                self._refresh()
                return False

        def do_focus_in(self):
            self._sync()
            if self._props is not None:
                self.register_properties(self._props)
                self._update_mode_prop()

        def do_focus_out(self):
            # 入力途中のまま別の場所へ移ったら、書きかけは捨てる
            self._session.reset()
            self._refresh()

        def do_reset(self):
            self._session.reset()
            self._refresh()

        def do_disable(self):
            self._session.reset()
            self._refresh()

        def do_page_up(self):
            return self._apply(self._session.handle(Key(name="Page_Up")))

        def do_page_down(self):
            return self._apply(self._session.handle(Key(name="Page_Down")))

        def do_cursor_up(self):
            return self._apply(self._session.handle(Key(name="Up")))

        def do_cursor_down(self):
            return self._apply(self._session.handle(Key(name="Down")))

        def do_candidate_clicked(self, index, button, state):
            s = self._session
            self._apply(s.select_index(s.page_start + index))

        def do_property_activate(self, prop_name, state):
            if prop_name == "mode":
                s = self._session
                s.cycle_mode()
                shared.mode = s.mode
                self._update_mode_prop()
                self._refresh()

    class EngineFactory(IBus.Factory):
        def __init__(self, bus):
            self._bus = bus
            self._n = 0
            super().__init__(connection=bus.get_connection(), object_path=IBus.PATH_FACTORY)

        def do_create_engine(self, engine_name):
            if engine_name != ENGINE_NAME:
                return None
            self._n += 1
            return C01Engine(self._bus, f"/org/freedesktop/IBus/Engine/C01/{self._n}")

    bus = IBus.Bus()
    if not bus.is_connected():
        print("ibus-daemon に接続できません。ibus が起動しているか確かめてください", file=sys.stderr)
        return 1
    loop = GLib.MainLoop()
    bus.connect("disconnected", lambda _b: loop.quit())
    factory = EngineFactory(bus)  # noqa: F841 - 生きている間だけエンジンを作れる

    if "--ibus" in argv:
        bus.request_name(BUS_NAME, 0)
    else:
        # ibus-daemon から起動されたのではない（手で動かした）ときは、自分で登録する
        comp = IBus.Component.new(BUS_NAME, "C01", __version__, "MIT", "C01", "", "", "c01")
        comp.add_engine(
            IBus.EngineDesc.new(
                ENGINE_NAME, "C01", "ローマ字の仮名と倉頡で漢字を統一入力", "ja", "MIT", "C01", "input-keyboard", "default"
            )
        )
        bus.register_component(comp)
    log.info("C01 エンジンを起動しました (v%s)", __version__)
    loop.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
