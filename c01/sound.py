"""エラー音を鳴らす。設定した音声ファイルを、入っているプレイヤーで再生する。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_PLAYERS = (
    ("pw-play", []),
    ("paplay", []),
    ("aplay", ["-q"]),
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
)


def play(path: str) -> bool:
    """鳴らせたら True。ファイル未設定・プレイヤーなしのときは何もしない。"""
    if not path:
        return False
    p = Path(path).expanduser()
    if not p.is_file():
        return False
    for exe, extra in _PLAYERS:
        found = shutil.which(exe)
        if found:
            try:
                subprocess.Popen(
                    [found, *extra, str(p)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True
            except OSError:
                continue
    return False
