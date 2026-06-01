"""Player log monitor for tracking position in Project Gorgon."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterator, NamedTuple, Optional

import src.config.config as config


PLAYER_LOG_PATTERN = "player.log"


class Position(NamedTuple):
    """Player position coordinates."""
    x: float
    y: float
    z: Optional[float] = None


class PlayerLogMonitor:
    """Monitors the player.log for position and other player data."""

    def __init__(self, log_dir: Optional[Path] = None, pattern: str = PLAYER_LOG_PATTERN):
        # Don't search for file during initialization - lazy load it
        self.log_dir = Path(log_dir) if log_dir else None
        self.pattern = pattern
        self.current_file: Optional[Path] = None
        self._position = 0
        self._last_position: Optional[Position] = None
        self._file_checked = False  # Cache whether we've checked for the file

    def _find_log_file_quick(self) -> Optional[Path]:
        """Quickly find the player.log file with minimal filesystem checks."""
        # If log_dir is provided, just check there
        if self.log_dir is not None:
            # Check for Player.log (capital P)
            player_log = self.log_dir / "Player.log"
            if player_log.exists():
                return player_log
            # Check lowercase
            player_log_lower = self.log_dir / "player.log"
            if player_log_lower.exists():
                return player_log_lower
            return None

        # If no log_dir provided, try PG_BASE first (fastest)
        if hasattr(config, 'PG_BASE') and config.PG_BASE:
            pg_base = Path(config.PG_BASE)
            player_log = pg_base / "Player.log"
            if player_log.exists():
                return player_log
            player_log_lower = pg_base / "player.log"
            if player_log_lower.exists():
                return player_log_lower

        # Fallback to default location only if needed
        home = Path.home()
        default_path = home / ".config" / "unity3d" / "Elder Game" / "Project Gorgon"
        player_log = default_path / "Player.log"
        if player_log.exists():
            return player_log

        return None

    def _switch_to_newest_if_needed(self) -> bool:
        """Ensure self.current_file points to an existing log file.

        This will try to discover the log file when absent and handle
        replacement/rotation by switching and resetting the read position.
        Returns True if the current file changed or was found.
        """
        # If we don't yet have a file, try to find one now (keep retrying)
        if self.current_file is None or not self.current_file.exists():
            new_file = self._find_log_file_quick()
            if new_file is None:
                # still not found
                return False
            # If file changed (or first time), switch and reset position
            if self.current_file is None or new_file.resolve() != self.current_file.resolve():
                self.current_file = new_file
                try:
                    # Start tailing at EOF so we don't enqueue the entire historical log
                    self._position = int(new_file.stat().st_size)
                except Exception:
                    self._position = 0
                return True
            return False

        # If we have a current file that no longer exists, attempt to find replacement
        if not self.current_file.exists():
            new_file = self._find_log_file_quick()
            if new_file and new_file.resolve() != (self.current_file.resolve() if self.current_file else None):
                self.current_file = new_file
                try:
                    self._position = int(new_file.stat().st_size)
                except Exception:
                    self._position = 0
                return True
        return False

    def read_new_lines(self) -> list[str]:
        """Reads new lines from the player log file."""
        self._switch_to_newest_if_needed()
        if self.current_file is None:
            return []

        try:
            with self.current_file.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self._position)
                lines = f.readlines()
                self._position = f.tell()

            return [line.rstrip("\n") for line in lines]
        except Exception:
            # If file read fails, return empty list
            return []

    def parse_position(self, line: str) -> Optional[Position]:
        """Parse position coordinates from a log line.
        
        Project Gorgon specific patterns:
        - "SPAWNING LOCAL PLAYER AT (1419.65, 43.75, 1527.75)"
        - "LocalPlayer: ProcessNewPosition((1.25, 0.00, 12.50), ...)"
        
        Common Unity patterns:
        - "Position: (123.45, 67.89, 0.00)"
        - "Player pos: x=123.45 y=67.89 z=0.00"
        """
        # Pattern 1: SPAWNING LOCAL PLAYER AT (x, y, z)
        match = re.search(r"SPAWNING LOCAL PLAYER AT \(([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)\)", line)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            z = float(match.group(3))
            return Position(x, y, z)
        
        # Pattern 2: ProcessNewPosition((x, y, z), ...)
        match = re.search(r"ProcessNewPosition\(\(([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)\)", line)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            z = float(match.group(3))
            return Position(x, y, z)
        
        # Pattern 3: ProcessAddPlayer(..., (x, y, z))
        match = re.search(r"ProcessAddPlayer\([^)]*\)\s*,\s*\(([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)\)", line)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            z = float(match.group(3))
            return Position(x, y, z)
        
        # Generic patterns for other Unity games
        # Pattern 4: (x, y, z) or (x, y)
        match = re.search(r"[Pp]osition.*?\(?(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)(?:\s*,\s*(-?\d+\.?\d*))?\)?", line)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            z = float(match.group(3)) if match.group(3) else None
            return Position(x, y, z)
        
        # Pattern 5: x=... y=... z=...
        match = re.search(r"[Pp]os.*?x[=:]\s*(-?\d+\.?\d*)\s+y[=:]\s*(-?\d+\.?\d*)(?:\s+z[=:]\s*(-?\d+\.?\d*))?", line)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            z = float(match.group(3)) if match.group(3) else None
            return Position(x, y, z)
        
        # Pattern 6: Location: x y
        match = re.search(r"[Ll]ocation[=:]\s*(-?\d+\.?\d*)\s*,?\s*(-?\d+\.?\d*)", line)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            return Position(x, y)
        
        # Pattern 7: Coords: [x, y]
        match = re.search(r"[Cc]oord.*?\[\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\]", line)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            return Position(x, y)
        
        return None

    def get_latest_position(self) -> Optional[Position]:
        """Read new lines and return the latest position found."""
        lines = self.read_new_lines()
        for line in lines:
            pos = self.parse_position(line)
            if pos:
                self._last_position = pos
        return self._last_position

    def stream(self, poll_interval: float = 1.0) -> Iterator[Position]:
        """Yields position updates continuously."""
        while True:
            pos = self.get_latest_position()
            if pos:
                yield pos
            time.sleep(poll_interval)


def monitor_player_position(log_dir: Optional[Path] = None, poll_interval: float = 1.0) -> Iterator[Position]:
    """Convenience generator for streaming player position updates."""
    monitor = PlayerLogMonitor(log_dir=log_dir)
    yield from monitor.stream(poll_interval=poll_interval)
