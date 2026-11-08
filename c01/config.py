"""設定ファイル（TOML）とデータ置き場の解決。"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
BUNDLED_DATA = PKG_DIR / "data"

MODE_NAMES = ("direct", "kanji", "hanwa")
SCRIPT_NAMES = ("all", "trad", "simp", "shin")

# 古い設定の読み替え
LEGACY_MODES = {"hanwa_hira": ("hanwa", "hiragana"), "hanwa_kata": ("hanwa", "katakana")}
# 廃止した項目（書いてあっても無視する）
OBSOLETE_KEYS = {
    "kanji_priority": "漢字優先リストは廃止しました（compound の首辞リストで指定します）",
    "hira2kata": "hira2kata は廃止しました（和漢混淆（片）は tail に片仮名の表を選んで行います）",
}


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
    # 起動時のモード: direct（直接入力）/ kanji（漢字のみ）/ hanwa（和漢混淆）
    mode: str = "hanwa"
    # head: 首辞になる字の表（data/head/<名前>.csv）。倉頡表・追加字。左から順に優先される
    head: list[str] = field(default_factory=lambda: ["cangjie5", "custom"])
    # tail: 尾辞（首辞のあとに続く仮名）の表（data/tail/<名前>.csv）。
    #   平仮名の表なら和漢混淆、片仮名の表なら和漢混淆（片）になる
    tail: str = "hiragana-hepburn"
    # pure: 単独で構成するもの（data/pure/<名前>.csv）。片仮名など。いつも最低優先度の候補として並行して変換される
    pure: list[str] = field(default_factory=lambda: ["katakana-hepburn"])
    # compound: 複合首辞のリスト（data/compound/<名前>.txt）。熟語・送り仮名・首辞となる仮名。左から順に優先される
    compound: list[str] = field(default_factory=lambda: ["jukugo", "okurigana", "kana_head"])
    # ワイルドカード（る* など）の展開表: data/wildcards/<名前>.csv
    wildcards: str = "default"
    # data/symbols/<名前>.csv
    symbols: str = "default"
    # 文字の分類表（繁体・簡体・新字体の判定用）: data/variants/<名前>.csv。空なら未使用
    variants: str = ""
    # all / trad / simp / shin
    script: str = "all"
    # latin: 打ったアルファベットのまま / map: preedit_map の表で置き換える
    preedit: str = "latin"
    preedit_map: str = "cangjie5"
    # エラー音の音声ファイル（空なら鳴らさない）
    error_sound: str = ""
    # 候補窓の1ページの件数（数字キー 0〜9 で選ぶので 10 まで）
    page_size: int = 10
    # 首辞の後ろに尾辞が続く候補で、1つの打鍵長につき出す字の最大数（全体が1字で読める候補には効かない）
    max_split_kanji: int = 3
    # モードを順に切り替えるキー
    mode_keys: list[str] = field(default_factory=lambda: ["ctrl+shift+m"])
    # 読み込み時の注意（設定ファイルの項目ではない）
    notes: list[str] = field(default_factory=list, metadata={"internal": True})

    def validate(self) -> None:
        if self.mode not in MODE_NAMES:
            raise ConfigError(f"mode は {MODE_NAMES} のどれか: {self.mode!r}")
        if not self.tail:
            raise ConfigError("tail には表の名前を書いてください（例: hiragana-hepburn）")
        if self.script not in SCRIPT_NAMES:
            raise ConfigError(f"script は {SCRIPT_NAMES} のどれか: {self.script!r}")
        if self.preedit not in ("latin", "map"):
            raise ConfigError(f"preedit は latin か map: {self.preedit!r}")
        if not self.head:
            raise ConfigError("head には表を1つ以上書いてください")
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
        raw = _migrate(raw, cfg)
        known = {f.name for f in fields(Config) if not f.metadata.get("internal")}
        unknown = set(raw) - known
        if unknown:
            raise ConfigError(f"{p}: 未知の設定項目 {sorted(unknown)}（使えるのは {sorted(known)}）")
        for k, v in raw.items():
            setattr(cfg, k, v)
    cfg.validate()
    return cfg


def _migrate(raw: dict, cfg: Config) -> dict:
    """古い設定の書き方を新しいものに読み替える。"""
    raw = dict(raw)
    for key, why in OBSOLETE_KEYS.items():
        if key in raw:
            del raw[key]
            cfg.notes.append(why)
    if raw.get("mode") in LEGACY_MODES:
        raw["mode"], tail = LEGACY_MODES[raw["mode"]]
        raw.setdefault("tail", tail)
        cfg.notes.append("mode の hanwa_hira / hanwa_kata は hanwa + tail に読み替えました")
    if "cangjie" in raw or "cangjie_extra" in raw:
        names = [raw.pop("cangjie", "cangjie5")] + list(raw.pop("cangjie_extra", []))
        raw.setdefault("head", names)
        cfg.notes.append("cangjie / cangjie_extra は head に読み替えました")
    # 仮名表: romaji / hiragana / katakana と、種類だけを書いた tail（hiragana / katakana）
    old_tail = raw.get("tail") in ("hiragana", "katakana")
    if any(k in raw for k in ("romaji", "hiragana", "katakana")) or old_tail:
        romaji = raw.pop("romaji", "hepburn")
        hira = raw.pop("hiragana", "") or romaji
        kata = raw.pop("katakana", "") or romaji
        kind = raw["tail"] if old_tail else "hiragana"
        raw["tail"] = f"{kind}-{hira if kind == 'hiragana' else kata}"
        raw.setdefault("pure", [f"katakana-{kata}"])
        cfg.notes.append(
            f"romaji / hiragana / katakana は tail = {raw['tail']!r}、pure = {raw['pure']!r} に読み替えました"
        )
    return raw


# 新しい置き場所 → 古い置き場所（利用者が前の配置のまま持っている表も読めるように）
_LEGACY = (
    (re.compile(r"^head/(.+)$"), r"cangjie/\1"),
    (re.compile(r"^tail/hiragana-(.+)\.csv$"), r"romaji/\1/hiragana.csv"),
    (re.compile(r"^tail/katakana-(.+)\.csv$"), r"romaji/\1/katakana.csv"),
    (re.compile(r"^pure/katakana-(.+)\.csv$"), r"romaji/\1/katakana.csv"),
)


def _legacy_paths(rel: str) -> list[str]:
    return [pat.sub(repl, rel) for pat, repl in _LEGACY if pat.match(rel)]


def find_data(rel: str) -> Path:
    """利用者のデータ置き場を先に、なければ同梱のデータから探す。
    それでも無ければ、古い配置（cangjie/ や romaji/<方式>/）の利用者の表を探す。"""
    tried = []
    for root in (user_data_dir(), BUNDLED_DATA):
        p = root / rel
        tried.append(str(p))
        if p.exists():
            return p
    for old in _legacy_paths(rel):
        p = user_data_dir() / old
        tried.append(str(p))
        if p.exists():
            return p
    raise FileNotFoundError(f"{rel} が見つかりません。探した場所: {', '.join(tried)}")


def list_choices(subdir: str) -> list[str]:
    """設定で選べる名前の一覧（同名は1つ。利用者の分も入る）。"""
    names: set[str] = set()
    for root in (user_data_dir(), BUNDLED_DATA):
        d = root / subdir
        if not d.is_dir():
            continue
        for e in d.iterdir():
            if e.is_dir():
                names.add(e.name)
            elif e.suffix in (".csv", ".txt") and e.stem.lower() != "readme":
                names.add(e.stem)
    return sorted(names)
