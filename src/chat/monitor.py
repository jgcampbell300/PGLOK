from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator, Optional

import src.config.config as config


CHAT_LOG_PATTERN = "Chat-*-*-*.log"


class ChatLogMonitor:
    """Monitors the newest Project Gorgon chat log and tails new lines."""

    def __init__(self, chat_dir: Optional[Path] = None, pattern: str = CHAT_LOG_PATTERN):
        self.chat_dir = Path(chat_dir) if chat_dir else self._default_chat_dir()
        self.pattern = pattern
        self.current_file: Optional[Path] = None
        self._position = 0

    @staticmethod
    def _default_chat_dir() -> Path:
        if config.CHAT_DIR is None:
            raise ValueError("config.CHAT_DIR is not set. Run locate/initialize first.")
        return Path(config.CHAT_DIR)

    def find_newest_log(self) -> Optional[Path]:
        if not self.chat_dir.exists():
            return None
        candidates = list(self.chat_dir.glob(self.pattern))
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def _switch_to_newest_if_needed(self) -> bool:
        newest = self.find_newest_log()
        if newest is None:
            return False

        if self.current_file is None or newest != self.current_file:
            self.current_file = newest
            self._position = 0
            return True

        return False

    def read_new_lines(self) -> list[str]:
        """Reads new lines from the current newest log file."""
        self._switch_to_newest_if_needed()
        if self.current_file is None:
            return []

        with self.current_file.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(self._position)
            lines = f.readlines()
            self._position = f.tell()

        return [line.rstrip("\n") for line in lines]

    def stream(self, poll_interval: float = 1.0) -> Iterator[str]:
        """Yields new log lines continuously, switching files when a newer one appears."""
        while True:
            for line in self.read_new_lines():
                yield line
            time.sleep(poll_interval)


def monitor_newest_chat_log(chat_dir: Optional[Path] = None, poll_interval: float = 1.0) -> Iterator[str]:
    """Convenience generator for streaming newest chat log lines."""
    monitor = ChatLogMonitor(chat_dir=chat_dir)
    yield from monitor.stream(poll_interval=poll_interval)
