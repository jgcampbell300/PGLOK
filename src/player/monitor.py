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
        self.log_dir = Path(log_dir) if log_dir else self._default_log_dir()
        self.pattern = pattern
        self.current_file: Optional[Path] = None
        self._position = 0
        self._last_position: Optional[Position] = None

    @staticmethod
    def _default_log_dir() -> Path:
        """Find the default player.log directory."""
        home = Path.home()
        
        possible_paths = [
            # Unity standard location on Linux
            home / ".config" / "unity3d" / "Elder Game" / "Project Gorgon",
            home / ".config" / "unity3d" / "ElderGame" / "Project Gorgon",
            # Other common locations
            home / "Project Gorgon",
            home / "Documents" / "Project Gorgon",
            home / "My Games" / "Project Gorgon",
            home / "AppData" / "Local" / "Project Gorgon",
            home / "Library" / "Application Support" / "Project Gorgon",  # macOS
            Path("C:/") / "Program Files (x86)" / "Steam" / "steamapps" / "common" / "Project Gorgon",
            Path("C:/") / "Program Files" / "Steam" / "steamapps" / "common" / "Project Gorgon",
        ]
        
        # Check config for PG_BASE
        if hasattr(config, 'PG_BASE') and config.PG_BASE:
            possible_paths.insert(0, Path(config.PG_BASE))
        
        for path in possible_paths:
            if path.exists():
                # Check for Player.log (Unity uses capital P)
                player_log = path / "Player.log"
                if player_log.exists():
                    return path
                # Also check lowercase
                player_log_lower = path / "player.log"
                if player_log_lower.exists():
                    return path
                # Check Logs subdirectory
                logs_dir = path / "Logs"
                if logs_dir.exists() and (logs_dir / "player.log").exists():
                    return logs_dir
        
        # Fallback - return first possible path and let it fail gracefully
        return possible_paths[0] if possible_paths else home / "Project Gorgon"

    def find_log_file(self) -> Optional[Path]:
        """Find the player.log file."""
        if not self.log_dir.exists():
            return None
        
        # Check for Player.log (Unity standard with capital P)
        player_log = self.log_dir / "Player.log"
        if player_log.exists():
            return player_log
        
        # Also check lowercase variant
        player_log_lower = self.log_dir / "player.log"
        if player_log_lower.exists():
            return player_log_lower
        
        # Check parent directory for both cases
        parent_log = self.log_dir.parent / "Player.log"
        if parent_log.exists():
            return parent_log
        
        parent_log_lower = self.log_dir.parent / "player.log"
        if parent_log_lower.exists():
            return parent_log_lower
        
        return None

    def _switch_to_newest_if_needed(self) -> bool:
        """Check if we need to switch to a newer log file."""
        newest = self.find_log_file()
        if newest is None:
            return False

        if self.current_file is None or newest != self.current_file:
            self.current_file = newest
            self._position = 0
            return True

        return False

    def read_new_lines(self) -> list[str]:
        """Reads new lines from the player log file."""
        self._switch_to_newest_if_needed()
        if self.current_file is None:
            return []

        with self.current_file.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(self._position)
            lines = f.readlines()
            self._position = f.tell()

        return [line.rstrip("\n") for line in lines]

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
