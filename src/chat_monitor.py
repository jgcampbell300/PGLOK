from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from src.chat.monitor import CHAT_LOG_PATTERN, ChatLogMonitor as _ChatLogMonitor, monitor_newest_chat_log
from src.timer_db import DEFAULT_BOSS_DURATIONS, DEFAULT_TIMER_DURATIONS, TimerDatabase


class ChatLogMonitor(_ChatLogMonitor):
    """Compatibility wrapper for older imports.

    The project now uses src.chat.monitor.ChatLogMonitor as the canonical
    implementation. This wrapper keeps the legacy src.chat_monitor import path
    working for any older callers that still expect an optional timer_db
    argument and timer event helpers.
    """

    def __init__(
        self,
        chat_dir: Optional[Path] = None,
        timer_db: Optional[TimerDatabase] = None,
        pattern: str = CHAT_LOG_PATTERN,
    ):
        super().__init__(chat_dir=chat_dir, pattern=pattern)
        self.timer_db = timer_db
        if self.timer_db is not None:
            self._ensure_default_durations()

    def _ensure_default_durations(self) -> None:
        """Seed the timer database with known durations if it is empty."""
        try:
            if not self.timer_db.get_timer_durations():
                self.timer_db.initialize_default_durations()
        except Exception:
            pass

        try:
            if not self.timer_db.get_boss_durations():
                self.timer_db.initialize_boss_durations()
        except Exception:
            pass

    def scan_chat_logs(self) -> List[Dict]:
        """Compatibility method that scans the newest log and returns parsed events."""
        events: List[Dict] = []
        for line in self.read_new_lines():
            event = self._parse_line(line)
            if event:
                events.append(event)
        return events

    def _parse_line(self, line: str) -> Optional[Dict]:
        """Parse a line into a minimal legacy event format."""
        if not line:
            return None

        lowered = line.lower()
        if "boss" in lowered:
            return self._create_event("boss", line)
        for key in ("planting", "retting", "fletching", "bundle", "cooking", "brewing", "crafting"):
            if key in lowered:
                return self._create_event(key, line)
        return None

    def _create_event(self, category: str, full_line: str) -> Dict:
        """Create a simplified event record for compatibility callers."""
        event_type = category
        event_name = category
        duration_seconds = 0
        description = full_line.strip() or category.title()

        if category == "boss":
            event_type = "boss"
            duration_seconds = next(iter(DEFAULT_BOSS_DURATIONS.values()))["duration"] if DEFAULT_BOSS_DURATIONS else 0
        elif category in DEFAULT_TIMER_DURATIONS:
            duration_seconds = DEFAULT_TIMER_DURATIONS[category]["duration"]

        return {
            "event_type": event_type,
            "event_name": event_name,
            "action": "start",
            "duration_seconds": duration_seconds,
            "description": description,
            "timestamp": None,
            "source_line": full_line,
        }

    def process_events(self, events: List[Dict]) -> List[str]:
        """Process detected events using the attached timer database."""
        actions: List[str] = []
        if self.timer_db is None:
            return actions

        for event in events:
            action = self._handle_event(event)
            if action:
                actions.append(action)
        return actions

    def _handle_event(self, event: Dict) -> Optional[str]:
        """Handle a compatibility event."""
        if self.timer_db is None:
            return None

        event_type = str(event.get("event_type", ""))
        event_name = str(event.get("event_name", ""))
        action = str(event.get("action", "start"))

        if action == "start":
            timer_id = self.timer_db.start_timer(
                event_type,
                event_name,
                f"Auto-started from chat: {event.get('description', event_name)}",
            )
            return f"Started timer for {event.get('description', event_name)} (ID: {timer_id})"

        if action == "finish":
            active_timers = self.timer_db.get_active_timers()
            for timer in active_timers:
                if timer["event_type"] == event_type:
                    completed = self.timer_db.stop_timer(timer["id"], "completed")
                    if completed:
                        duration_str = self._format_duration(completed["duration_seconds"])
                        return f"Completed timer for {event.get('description', event_name)} - Duration: {duration_str}"

        return None

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds}s"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"

    def initialize_default_durations(self):
        """Mirror the legacy API for callers that expect to seed defaults."""
        if self.timer_db is None:
            return
        for event_key, event_data in DEFAULT_TIMER_DURATIONS.items():
            category, item = event_key.split(":", 1)
            self.timer_db.add_timer_duration(
                category,
                item,
                event_data["duration"],
                event_data["description"],
                category,
            )


__all__ = [
    "CHAT_LOG_PATTERN",
    "ChatLogMonitor",
    "DEFAULT_BOSS_DURATIONS",
    "DEFAULT_TIMER_DURATIONS",
    "monitor_newest_chat_log",
]
