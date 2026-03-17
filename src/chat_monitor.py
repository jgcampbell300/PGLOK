import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from timer_db import TimerDatabase, DEFAULT_TIMER_DURATIONS


class ChatLogMonitor:
    """Monitors chat logs for game events that should trigger timers."""
    
    def __init__(self, chat_dir: Path, timer_db: TimerDatabase):
        self.chat_dir = chat_dir
        self.timer_db = timer_db
        self.last_position = {}  # Track last read position per file
        
        # Regex patterns for detecting game events
        self.event_patterns = {
            # Planting events
            'planting': [
                re.compile(r'You plant (?:a )?(\w+) seeds?', re.IGNORECASE),
                re.compile(r'You harvest (?:a )?(\w+)', re.IGNORECASE),  # Harvest might trigger new planting
            ],
            
            # Retting events
            'retting': [
                re.compile(r'You begin retting (\w+)', re.IGNORECASE),
                re.compile(r'You finish retting (\w+)', re.IGNORECASE),
            ],
            
            # Fletching events
            'fletching': [
                re.compile(r'You begin fletching (\w+)', re.IGNORECASE),
                re.compile(r'You finish fletching (\w+)', re.IGNORECASE),
                re.compile(r'You fletch (\d+) (\w+)', re.IGNORECASE),
            ],
            
            # Bundle creation events
            'bundle': [
                re.compile(r'You create (?:a )?(\w+) bundle', re.IGNORECASE),
                re.compile(r'You bundle (?:a )?(\w+)', re.IGNORECASE),
            ],
            
            # Cooking/brewing events
            'cooking': [
                re.compile(r'You begin cooking (\w+)', re.IGNORECASE),
                re.compile(r'You finish cooking (\w+)', re.IGNORECASE),
            ],
            'brewing': [
                re.compile(r'You begin brewing (\w+)', re.IGNORECASE),
                re.compile(r'You finish brewing (\w+)', re.IGNORECASE),
            ],
            
            # Crafting events
            'crafting': [
                re.compile(r'You begin crafting (\w+)', re.IGNORECASE),
                re.compile(r'You finish crafting (\w+)', re.IGNORECASE),
            ],
            
            # Boss events
            'boss': [
                re.compile(r'You have entered (?:the )?(\w+(?: \w+)*) (?:lair|cave|tomb|plane|warren)', re.IGNORECASE),
                re.compile(r'(\w+(?: \w+)*) (?:appears|emerges|arrives)', re.IGNORECASE),
                re.compile(r'You begin fighting (?:the )?(\w+(?: \w+)*)', re.IGNORECASE),
                re.compile(r'(\w+(?: \w+)*) (?:has been|is) (?:defeated|killed)', re.IGNORECASE),
                re.compile(r'You have defeated (?:the )?(\w+(?: \w+)*)', re.IGNORECASE),
                re.compile(r'(\w+(?: \w+)*) (?:roars|growls|shouts)', re.IGNORECASE),
            ],
        }
    
    def scan_chat_logs(self) -> List[Dict]:
        """Scan chat logs for new timer events."""
        events = []
        
        if not self.chat_dir.exists():
            return events
        
        # Get all chat log files
        chat_files = list(self.chat_dir.glob("*.log"))
        chat_files.extend(self.chat_dir.glob("*.txt"))
        
        for chat_file in chat_files:
            events.extend(self._scan_file(chat_file))
        
        return events
    
    def _scan_file(self, file_path: Path) -> List[Dict]:
        """Scan a single chat log file for events."""
        events = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Get file size and seek to last position
                f.seek(0, 2)  # Seek to end
                file_size = f.tell()
                
                # Start from beginning if we haven't read this file before
                last_pos = self.last_position.get(str(file_path), 0)
                f.seek(last_pos)
                
                # Read new lines
                new_lines = f.readlines()
                
                # Update position for next time
                self.last_position[str(file_path)] = file_size
                
                # Process each line for events
                for line in new_lines:
                    event = self._parse_line(line.strip())
                    if event:
                        events.append(event)
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
        
        return events
    
    def _parse_line(self, line: str) -> Optional[Dict]:
        """Parse a single chat line for timer events."""
        if not line:
            return None
        
        # Check each event category
        for category, patterns in self.event_patterns.items():
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    return self._create_event(category, match, line)
        
        return None
    
    def _create_event(self, category: str, match, full_line: str) -> Dict:
        """Create an event dictionary from a regex match."""
        if category == 'planting':
            item = match.group(1).lower()
            event_type = f"planting:{item}"
            # Map common items to known durations
            if f"planting:{item}" in DEFAULT_TIMER_DURATIONS:
                duration = DEFAULT_TIMER_DURATIONS[f"planting:{item}"]["duration"]
                description = DEFAULT_TIMER_DURATIONS[f"planting:{item}"]["description"]
            else:
                duration = 300  # Default 5 minutes
                description = f"Planting {item}"
            
            action = "start" if "plant" in full_line.lower() else "harvest"
            
        elif category == 'retting':
            item = match.group(1).lower()
            event_type = f"retting:{item}"
            if f"retting:{item}" in DEFAULT_TIMER_DURATIONS:
                duration = DEFAULT_TIMER_DURATIONS[f"retting:{item}"]["duration"]
                description = DEFAULT_TIMER_DURATIONS[f"retting:{item}"]["description"]
            else:
                duration = 600  # Default 10 minutes
                description = f"Retting {item}"
            
            action = "start" if "begin retting" in full_line.lower() else "finish"
            
        elif category == 'fletching':
            # Check if it's a specific type or general
            if len(match.groups()) >= 2:
                quantity = match.group(1)
                item = match.group(2).lower()
                event_type = f"fletching:{item}"
            else:
                item = match.group(1).lower()
                event_type = f"fletching:{item}"
                quantity = "1"
            
            if f"fletching:{item}" in DEFAULT_TIMER_DURATIONS:
                duration = DEFAULT_TIMER_DURATIONS[f"fletching:{item}"]["duration"]
                description = DEFAULT_TIMER_DURATIONS[f"fletching:{item}"]["description"]
            else:
                duration = 60  # Default 1 minute
                description = f"Fletching {item}"
            
            action = "start" if "begin fletching" in full_line.lower() else "finish"
            
        elif category == 'bundle':
            item = match.group(1).lower()
            event_type = f"bundle:{item}"
            if f"bundle:{item}" in DEFAULT_TIMER_DURATIONS:
                duration = DEFAULT_TIMER_DURATIONS[f"bundle:{item}"]["duration"]
                description = DEFAULT_TIMER_DURATIONS[f"bundle:{item}"]["description"]
            else:
                duration = 30  # Default 30 seconds
                description = f"Creating {item} bundle"
            
            action = "start"
            
        elif category in ['cooking', 'brewing', 'crafting']:
            item = match.group(1).lower()
            event_type = f"{category}:{item}"
            
            # Get duration from defaults or use reasonable defaults
            if event_type in DEFAULT_TIMER_DURATIONS:
                duration = DEFAULT_TIMER_DURATIONS[event_type]["duration"]
                description = DEFAULT_TIMER_DURATIONS[event_type]["description"]
            else:
                duration = 120 if category == 'brewing' else 90  # 2 min for brewing, 1.5 min for others
                description = f"{category.title()} {item}"
            
            action = "start" if f"begin {category}" in full_line.lower() else "finish"
        
        elif category == 'boss':
            from timer_db import DEFAULT_BOSS_DURATIONS
            item = match.group(1).lower()
            event_type = f"boss:{item}"
            
            # Map boss names to known durations
            boss_key = None
            for key, data in DEFAULT_BOSS_DURATIONS.items():
                if item in key.lower() or key.lower() in item:
                    boss_key = key
                    break
            
            if boss_key:
                duration = DEFAULT_BOSS_DURATIONS[boss_key]["duration"]
                description = DEFAULT_BOSS_DURATIONS[boss_key]["description"]
            else:
                duration = 900  # Default 15 minutes for unknown bosses
                description = f"Boss Fight: {item.title()}"
            
            # Determine action based on context
            if any(word in full_line.lower() for word in ['entered', 'appears', 'emerges', 'arrives', 'fighting', 'roars', 'growls', 'shouts']):
                action = "start"
            elif any(word in full_line.lower() for word in ['defeated', 'killed']):
                action = "finish"
            else:
                action = "start"  # Default to start for ambiguous boss events
        
        else:
            return None
        
        return {
            'event_type': event_type,
            'event_name': item,
            'action': action,
            'duration_seconds': duration,
            'description': description,
            'timestamp': datetime.now(),
            'source_line': full_line
        }
    
    def process_events(self, events: List[Dict]) -> List[str]:
        """Process detected events and return timer actions."""
        actions = []
        
        for event in events:
            action = self._handle_event(event)
            if action:
                actions.append(action)
        
        return actions
    
    def _handle_event(self, event: Dict) -> Optional[str]:
        """Handle a single event and return appropriate action."""
        event_type = event['event_type']
        action = event['action']
        
        if action == 'start':
            # Start a timer for this event
            timer_id = self.timer_db.start_timer(
                event_type, 
                event['event_name'], 
                f"Auto-started from chat: {event['description']}"
            )
            return f"Started timer for {event['description']} (ID: {timer_id})"
        
        elif action == 'finish':
            # Stop any active timer for this event type
            active_timers = self.timer_db.get_active_timers()
            for timer in active_timers:
                if timer['event_type'] == event_type:
                    completed = self.timer_db.stop_timer(timer['id'], 'completed')
                    duration_str = self._format_duration(completed['duration_seconds'])
                    return f"Completed timer for {event['description']} - Duration: {duration_str}"
        
        elif action == 'harvest':
            # Harvest might trigger a new planting cycle
            # First stop any active planting timer
            active_timers = self.timer_db.get_active_timers()
            for timer in active_timers:
                if timer['event_type'].startswith('planting:'):
                    self.timer_db.stop_timer(timer['id'], 'harvested')
                    duration_str = self._format_duration(timer['duration_seconds'])
                    actions.append(f"Harvested - {timer['event_name']} timer stopped after {duration_str}")
            
            # Then start new timer if it's a planting action
            timer_id = self.timer_db.start_timer(
                event_type, 
                event['event_name'], 
                f"Auto-started after harvest: {event['description']}"
            )
            return f"Started new planting timer for {event['description']} (ID: {timer_id})"
        
        return None
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in a human-readable way."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"
    
    def initialize_default_durations(self):
        """Initialize the database with default timer durations."""
        for event_key, event_data in DEFAULT_TIMER_DURATIONS.items():
            category, item = event_key.split(':', 1)
            self.timer_db.add_timer_duration(
                category, 
                item, 
                event_data['duration'], 
                event_data['description'], 
                category
            )
