"""キー操作の状態管理。ibus には依存せず、単体でテストできる。

ibus 側（ibus_engine.py）は、キーを Key に直して handle() を呼び、
返ってきた Result と、preedit / candidates / cursor の状態を画面に反映するだけにする。
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .core import MODE_ORDER, Interpreter, Mode
from .tables import Compiled

NAMED_KEYS = {
    "space", "BackSpace", "Return", "Escape", "Tab",
    "Up", "Down", "Left", "Right", "Page_Up", "Page_Down", "Home", "End", "Delete",
}


@dataclass
class Key:
    """name: 名前つきキー（NAMED_KEYS のどれか）。char: 印字できる1文字（space は ' '）。"""

    name: str = ""
    char: str = ""
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    super: bool = False


@dataclass
class Result:
    handled: bool = False
    commit: str = ""
    error: bool = False


def parse_key_spec(spec: str) -> tuple[bool, bool, bool, bool, str]:
    """'ctrl+shift+m' → (ctrl, alt, shift, super, 'm')"""
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"キーの指定が空です: {spec!r}")
    mods = {"ctrl": False, "alt": False, "shift": False, "super": False}
    for p in parts[:-1]:
        p = p.lower()
        if p not in mods:
            raise ValueError(f"修飾キーは ctrl/alt/shift/super: {spec!r}")
        mods[p] = True
    last = parts[-1]
    return mods["ctrl"], mods["alt"], mods["shift"], mods["super"], last


class Session:
    def __init__(self, compiled: Compiled, config: Config, mode: Mode | None = None):
        self.c = compiled
        self.cfg = config
        self.interp = Interpreter(compiled, config.max_split_kanji)
        self.mode = mode or Mode(config.mode)
        self.page_size = config.page_size
        self.buf = ""
        self.cands: list[str] = []
        self.cursor = 0
        self._mode_keys = [parse_key_spec(s) for s in config.mode_keys]

    # --- 画面に出す状態 ------------------------------------------------
    @property
    def preedit(self) -> str:
        if self.cfg.preedit == "map":
            m = self.c.preedit_map
            return "".join(m.get(ch, ch) for ch in self.buf)
        return self.buf

    @property
    def page_start(self) -> int:
        return (self.cursor // self.page_size) * self.page_size

    def reset(self) -> None:
        self.buf = ""
        self.cands = []
        self.cursor = 0

    # --- 内部 ----------------------------------------------------------
    def _recompute(self) -> None:
        self.cands = self.interp.candidates(self.buf, self.mode)
        self.cursor = 0

    def _is_mode_key(self, key: Key) -> bool:
        for ctrl, alt, shift, sup, last in self._mode_keys:
            if (ctrl, alt, shift, sup) != (key.ctrl, key.alt, key.shift, key.super):
                continue
            if key.name and key.name.lower() == last.lower():
                return True
            if key.char and key.char.lower() == last.lower():
                return True
        return False

    def cycle_mode(self) -> Mode:
        i = MODE_ORDER.index(self.mode)
        self.mode = MODE_ORDER[(i + 1) % len(MODE_ORDER)]
        self.reset()
        return self.mode

    def _commit_index(self, idx: int, suffix: str = "") -> Result:
        text = self.cands[idx] + suffix
        self.reset()
        return Result(handled=True, commit=text)

    def _error(self) -> Result:
        return Result(handled=True, error=True)

    def select_index(self, idx: int) -> Result:
        """候補の番号を直接指定して確定する（マウスで候補を押したとき用）。"""
        if 0 <= idx < len(self.cands):
            return self._commit_index(idx)
        return self._error()

    # --- キー入力 ------------------------------------------------------
    def handle(self, key: Key) -> Result:
        if self._is_mode_key(key):
            self.cycle_mode()
            return Result(handled=True)

        if self.mode is Mode.DIRECT:
            return Result(handled=False)

        # Ctrl / Alt / Super つきのキーは、アプリのショートカットなのでそのまま渡す
        if key.ctrl or key.alt or key.super:
            return Result(handled=False)

        if not self.buf:
            return self._handle_empty(key)
        return self._handle_composing(key)

    def _handle_empty(self, key: Key) -> Result:
        ch = key.char
        if not ch or key.name in NAMED_KEYS and key.name != "space":
            return Result(handled=False)
        if ch == " ":
            return Result(handled=False)  # ふつうの空白はアプリに任せる
        if ch in self.c.buffer_chars and not key.shift:
            self.buf = ch
            self._recompute()
            return Result(handled=True)
        if ch in self.c.symbols:
            return Result(handled=True, commit=self.c.symbols[ch])
        return Result(handled=False)

    def _handle_composing(self, key: Key) -> Result:
        n = len(self.cands)
        name, ch = key.name, key.char

        if name == "space" or ch == " ":
            if n:
                return self._commit_index(self.cursor)
            return self._error()

        if ch.isdigit() and len(ch) == 1 and ch.isascii():
            idx = self.page_start + int(ch)
            if idx < n:
                return self._commit_index(idx)
            return self._error()

        if name == "Down":
            if n:
                self.cursor = (self.cursor + 1) % n
            return Result(handled=True)
        if name == "Up":
            if n:
                self.cursor = (self.cursor - 1) % n
            return Result(handled=True)
        if name == "Page_Down":
            if n:
                nxt = self.page_start + self.page_size
                self.cursor = nxt if nxt < n else 0
            return Result(handled=True)
        if name == "Page_Up":
            if n:
                if self.page_start - self.page_size >= 0:
                    self.cursor = self.page_start - self.page_size
                else:
                    self.cursor = ((n - 1) // self.page_size) * self.page_size
            return Result(handled=True)

        if name == "Return":
            text = self.buf  # 打った文字のまま確定（英単語などを書くとき用）
            self.reset()
            return Result(handled=True, commit=text)
        if name == "Escape":
            self.reset()
            return Result(handled=True)
        if name == "BackSpace":
            self.buf = self.buf[:-1]
            self._recompute()
            return Result(handled=True)
        if name in ("Left", "Right", "Home", "End", "Tab", "Delete"):
            return Result(handled=True)  # いまは何もしない（キーを食べるだけ）

        if ch and ch in self.c.buffer_chars and not key.shift:
            self.buf += ch
            self._recompute()
            return Result(handled=True)

        # 記号キー・大文字など: いまのまとまりを確定してから、その文字を入れる
        if ch and ch.isprintable():
            if not n:
                return self._error()
            suffix = self.c.symbols.get(ch, ch)
            return self._commit_index(self.cursor, suffix)

        return Result(handled=False)
