import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import json


class TimerDatabase:
    """Database for managing game timer events and durations."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """Initialize the timer database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS timer_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    description TEXT,
                    category TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS active_timers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    duration_seconds INTEGER,
                    status TEXT DEFAULT 'active',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS timer_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    completion_status TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for better performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timer_events_type ON timer_events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_active_timers_status ON active_timers(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timer_history_type ON timer_history(event_type)")
    
    def get_timer_durations(self) -> Dict[str, int]:
        """Get all predefined timer durations from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT event_type, event_name, duration_seconds, description 
                FROM timer_events 
                ORDER BY category, event_type, event_name
            """)
            
            durations = {}
            for row in cursor.fetchall():
                key = f"{row[0]}:{row[1]}"  # event_type:event_name
                durations[key] = {
                    'duration': row[2],
                    'description': row[3]
                }
        
        return durations
    
    def add_timer_duration(self, event_type: str, event_name: str, duration_seconds: int, 
                         description: str = "", category: str = ""):
        """Add or update a timer duration for an event."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO timer_events 
                (event_type, event_name, duration_seconds, description, category)
                VALUES (?, ?, ?, ?, ?)
            """, (event_type, event_name, duration_seconds, description, category))
    
    def start_timer(self, event_type: str, event_name: str, notes: str = "") -> int:
        """Start a new timer and return its ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO active_timers 
                (event_type, event_name, start_time, status, notes)
                VALUES (?, ?, CURRENT_TIMESTAMP, 'active', ?)
            """, (event_type, event_name, notes))
            return cursor.lastrowid
    
    def stop_timer(self, timer_id: int, completion_status: str = "completed") -> Optional[Dict]:
        """Stop an active timer and move it to history."""
        with sqlite3.connect(self.db_path) as conn:
            # Get the timer details
            cursor = conn.execute("""
                SELECT event_type, event_name, start_time, notes 
                FROM active_timers 
                WHERE id = ?
            """, (timer_id,))
            
            timer_info = cursor.fetchone()
            if not timer_info:
                return None
            
            # Calculate duration
            start_time = datetime.fromisoformat(timer_info[2])
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            
            # Move to history
            conn.execute("""
                INSERT INTO timer_history 
                (event_type, event_name, start_time, end_time, duration_seconds, completion_status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (timer_info[0], timer_info[1], timer_info[2], end_time, duration, completion_status, timer_info[3]))
            
            # Remove from active
            conn.execute("DELETE FROM active_timers WHERE id = ?", (timer_id,))
            
            return {
                'event_type': timer_info[0],
                'event_name': timer_info[1],
                'duration_seconds': duration,
                'completion_status': completion_status
            }
    
    def get_active_timers(self) -> List[Dict]:
        """Get all currently active timers."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, event_type, event_name, start_time, notes 
                FROM active_timers 
                WHERE status = 'active'
                ORDER BY start_time
            """)
            
            timers = []
            for row in cursor.fetchall():
                start_time = datetime.fromisoformat(row[3])
                current_duration = int((datetime.now() - start_time).total_seconds())
                
                timers.append({
                    'id': row[0],
                    'event_type': row[1],
                    'event_name': row[2],
                    'start_time': row[3],
                    'current_duration_seconds': current_duration,
                    'notes': row[4]
                })
        
        return timers
    
    def get_timer_history(self, limit: int = 50) -> List[Dict]:
        """Get timer history."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT event_type, event_name, start_time, end_time, 
                       duration_seconds, completion_status, notes 
                FROM timer_history 
                ORDER BY start_time DESC 
                LIMIT ?
            """, (limit,))
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    'event_type': row[0],
                    'event_name': row[1],
                    'start_time': row[2],
                    'end_time': row[3],
                    'duration_seconds': row[4],
                    'completion_status': row[5],
                    'notes': row[6]
                })
        
        return history
    
    def cancel_timer(self, timer_id: int) -> bool:
        """Cancel an active timer without moving to history."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE active_timers 
                SET status = 'cancelled' 
                WHERE id = ?
            """, (timer_id,))
            return cursor.rowcount > 0
    
    def initialize_default_durations(self):
        """Initialize database with default timer durations."""
        for event_key, event_data in DEFAULT_TIMER_DURATIONS.items():
            category, item = event_key.split(':', 1)
            self.add_timer_duration(
                category, 
                item, 
                event_data['duration'], 
                event_data['description'], 
                category
            )
    
    def get_boss_durations(self) -> Dict[str, int]:
        """Get all predefined boss timer durations from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT event_type, event_name, duration_seconds, description 
                FROM timer_events 
                WHERE event_type = 'boss'
                ORDER BY event_name
            """)
            
            durations = {}
            for row in cursor.fetchall():
                key = f"{row[0]}:{row[1]}"  # event_type:event_name
                durations[key] = {
                    'duration': row[2],
                    'description': row[3]
                }
        
        return durations
    
    def add_boss_duration(self, boss_name: str, duration_seconds: int, 
                         description: str = "", category: str = "boss"):
        """Add or update a boss timer duration."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO timer_events 
                (event_type, event_name, duration_seconds, description, category)
                VALUES (?, ?, ?, ?, ?)
            """, (category, boss_name, duration_seconds, description, category))
    
    def initialize_boss_durations(self):
        """Initialize database with default boss timer durations."""
        for event_key, event_data in DEFAULT_BOSS_DURATIONS.items():
            category, boss_name = event_key.split(':', 1)
            self.add_boss_duration(
                boss_name, 
                event_data['duration'], 
                event_data['description'], 
                category
            )
    
    def get_active_boss_timers(self) -> List[Dict]:
        """Get all currently active boss timers."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, event_type, event_name, start_time, notes 
                FROM active_timers 
                WHERE status = 'active' AND event_type = 'boss'
                ORDER BY start_time
            """)
            
            timers = []
            for row in cursor.fetchall():
                start_time = datetime.fromisoformat(row[3])
                current_duration = int((datetime.now() - start_time).total_seconds())
                
                timers.append({
                    'id': row[0],
                    'event_type': row[1],
                    'event_name': row[2],
                    'start_time': row[3],
                    'current_duration_seconds': current_duration,
                    'notes': row[4]
                })
        
        return timers


# Default timer durations for common Project Gorgon activities
DEFAULT_TIMER_DURATIONS = {
    # Planting timers (in seconds)
    "planting:carrot": {"duration": 180, "description": "Carrot growing time"},
    "planting:potato": {"duration": 300, "description": "Potato growing time"},
    "planting:wheat": {"duration": 240, "description": "Wheat growing time"},
    "planting:cotton": {"duration": 420, "description": "Cotton growing time"},
    "planting:flax": {"duration": 360, "description": "Flax growing time"},
    
    # Retting timers
    "retting:flax": {"duration": 600, "description": "Flax retting time"},
    
    # Fletching timers (in seconds)
    "fletching:arrow": {"duration": 45, "description": "Basic arrow fletching"},
    "fletching:crossbow": {"duration": 90, "description": "Crossbow bolt fletching"},
    "fletching:fire": {"duration": 120, "description": "Fire arrow fletching"},
    "fletching:frost": {"duration": 180, "description": "Frost arrow fletching"},
    "fletching:poison": {"duration": 240, "description": "Poison arrow fletching"},
    "fletching:electric": {"duration": 300, "description": "Electric arrow fletching"},
    
    # Bundle timers
    "bundle:flax": {"duration": 30, "description": "Flax bundle creation"},
    "bundle:herb": {"duration": 15, "description": "Herb bundle creation"},
    
    # Other activities
    "cooking:mushroom": {"duration": 60, "description": "Mushroom cooking"},
    "brewing:potion": {"duration": 120, "description": "Potion brewing"},
    "crafting:basic": {"duration": 90, "description": "Basic crafting"},
    "crafting:advanced": {"duration": 300, "description": "Advanced crafting"},
}

# Default boss timer durations for Project Gorgon bosses
DEFAULT_BOSS_DURATIONS = {
    # Dungeon bosses (in seconds)
    "boss:myconian_cave": {"duration": 900, "description": "Myconian Cave Boss (15 min)"},
    "boss:goblin_warren": {"duration": 720, "description": "Goblin Warren Boss (12 min)"},
    "boss:spider_lair": {"duration": 600, "description": "Spider Lair Boss (10 min)"},
    "boss:undead_tomb": {"duration": 840, "description": "Undead Tomb Boss (14 min)"},
    "boss:elemental_plane": {"duration": 1200, "description": "Elemental Plane Boss (20 min)"},
    
    # Raid bosses (in seconds)
    "boss:ancient_golem": {"duration": 1800, "description": "Ancient Golem (30 min)"},
    "boss:dragon_lair": {"duration": 2400, "description": "Dragon Lair Boss (40 min)"},
    "boss:demon_lord": {"duration": 2100, "description": "Demon Lord (35 min)"},
    "boss:lich_king": {"duration": 2700, "description": "Lich King (45 min)"},
    
    # World bosses (in seconds)
    "boss:giants": {"duration": 1500, "description": "Giants (25 min)"},
    "boss:kraken": {"duration": 1800, "description": "Kraken (30 min)"},
    "boss:phoenix": {"duration": 1200, "description": "Phoenix (20 min)"},
    
    # Event bosses (in seconds)
    "boss:halloween": {"duration": 900, "description": "Halloween Event Boss (15 min)"},
    "boss:winter": {"duration": 1200, "description": "Winter Event Boss (20 min)"},
    "boss:spring": {"duration": 600, "description": "Spring Event Boss (10 min)"},
}


    
def get_db_path(data_dir: Path) -> Path:
    """Get the timer database path."""
    return data_dir / "timers.db"
