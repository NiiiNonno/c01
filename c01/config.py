"""設定ファイル（TOML）とデータの置き場所の解決。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
BUNDLED_DATA = PKG_DIR / "data"

MODE_NAMES = ("direct", "kanji", "hanwa_hira", "hanwa_kata")
SCRIPT_NAMES = ("all", "trad", "simp", "shin")


def _env_dir(env: str, xdg_env: str, xdg_default: str) -> Path:
    if os.environ.get(env):
        return Path(os.environ[env]).expanduser()
    base = os.environ.get(xdg_env)
    root = Path(base) if base else Path.home() / xdg_default
    return root / "c01"


def user_config_dir() -> Path:
    return _env_dir("C01_CONFIG_DIR", "XDG_CONFIG_HOME", ".config")


def user_data_dir() -> Path:
    return _env_dir("C01_DATA_DIR", "XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    return _env_dir("C01_CACHE_DIR", "XDG_CACHE_HOME", ".cache")


def default_config_path() -> Path:
    return user_config_dir() / "config.toml"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    # 起動時のモード: direct / kanji / hanwa_hira / hanwa_kata
    mode: str = "hanwa_hira"
    # data/romaji/<名前>/ の下の hiragana.csv と katakana.csv
    romaji: str = "max"
    # data/symbols/<名前>.csv
    symbols: str = "default"
    # data/cangjie/<名前>.csv  （倉頡の本体。上から順が優先順位）
    cangjie: str = "cangjie5"
    # 倉頡に足す追加表（data/cangjie/<名前>.csv）。「々」「ヶ」など
    cangjie_extra: list[str] = field(default_factory=lambda: ["custom"])
    # 仮名より先に出す漢字の一覧: data/priority/<名前>.csv
    kanji_priority: str = "default"
    # 和漢混淆（片）で使う、平仮名→片仮名の置き換え表: data/hira2kata/<名前>.csv
    hira2kata: str = "default"
    # 文字の分類表（繁体・簡体・新字体の判定用）: data/variants/<名前>.csv。空なら未使用
    variants: str = ""
    # all / trad / simp / shin
    script: str = "all"
    # latin: 打ったアルファベットのまま / map: preedit_map の表で置き換える
    preedit: str = "latin"
    preedit_map: str = "cangjie5"
    # エラー音の音声ファイル（空なら鳴らさない）
    error_sound: str = ""
    # 候補の1ページの件数（数字キー 0〜9 で選ぶので 10 のまま推奨）
    page_size: int = 10
    # 「漢字＋仮名」の分割候補で、1つの倉頡コードにつき出す漢字の最大数
    max_split_kanji: int = 3
    # モード切り替えキー（順に direct → kanji → hanwa_hira → hanwa_kata → …）
    mode_keys: list[str] = field(default_factory=lambda: ["ctrl+shift+m"])

    def validate(self) -> None:
        if self.mode not in MODE_NAMES:
            raise ConfigError(f"mode は {MODE_NAMES} のどれか: {self.mode!r}")
        if self.script not in SCRIPT_NAMES:
            raise ConfigError(f"script は {SCRIPT_NAMES} のどれか: {self.script!r}")
        if self.preedit not in ("latin", "map"):
            raise ConfigError(f"preedit は latin か map: {self.preedit!r}")
        if not 1 <= self.page_size <= 10:
            raise ConfigError("page_size は 1〜10")
        if self.max_split_kanji < 1:
            raise ConfigError("max_split_kanji は 1 以上")


def load_config(path: str | os.PathLike | None = None) -> Config:
    p = Path(path) if path else default_config_path()
    cfg = Config()
    if p.exists():
        try:
            with open(p, "rb") as f:
                raw = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{p}: {e}") from e
        known = {f.name for f in fields(Config)}
        unknown = set(raw) - known
        if unknown:
            raise ConfigError(f"{p}: 未知の設定項目 {sorted(unknown)}（使えるのは {sorted(known)}）")
        for k, v in raw.items():
            setattr(cfg, k, v)
    cfg.validate()
    return cfg


def find_data(rel: str) -> Path:
    """利用者のデータ置き場を先に、なければ同梱データから探す。"""
    tried = []
    for root in (user_data_dir(), BUNDLED_DATA):
        p = root / rel
        tried.append(str(p))
        if p.exists():
            return p
    raise FileNotFoundError(f"{rel} が見つかりません。探した場所: {', '.join(tried)}")


def list_choices(subdir: str) -> list[str]:
    """設定で選べる名前の一覧（同梱＋利用者追加）。"""
    names: set[str] = set()
    for root in (user_data_dir(), BUNDLED_DATA):
        d = root / subdir
        if not d.is_dir():
            continue
        for e in d.iterdir():
            if e.is_dir():
                names.add(e.name)
            elif e.suffix == ".csv":
                names.add(e.stem)
    return sorted(names)
