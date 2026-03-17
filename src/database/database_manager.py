#!/usr/bin/env python3
"""
Unified Database Manager for PGLOK
Central database management for all PGLOK data
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from contextlib import contextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UnifiedDatabaseManager:
    """Unified database manager for all PGLOK data."""
    
    def __init__(self, db_path: Path):
        """Initialize database manager with database path."""
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._initialize_database()
        
        logger.info(f"Unified database initialized at {self.db_path}")
    
    def _initialize_database(self):
        """Initialize database with all schemas."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Enable foreign keys
            cursor.execute("PRAGMA foreign_keys = ON")
            
            # Run migrations
            self.run_migrations(conn)
            
            logger.info("Database initialization completed")
    
    @contextmanager
    def get_connection(self):
        """Get database connection with proper cleanup."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    
    def run_migrations(self, conn: sqlite3.Connection):
        """Run database migrations."""
        cursor = conn.cursor()
        
        # Create migrations table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Get applied migrations
        cursor.execute("SELECT filename FROM migrations ORDER BY filename")
        applied_migrations = {row['filename'] for row in cursor.fetchall()}
        
        # Migration files in order
        migration_files = [
            '001_initial_schema.sql',
            '002_addons_schema.sql',
            '003_farming_schema.sql'
        ]
        
        # Apply pending migrations
        for migration_file in migration_files:
            if migration_file not in applied_migrations:
                migration_path = Path(__file__).parent / "migrations" / migration_file
                if migration_path.exists():
                    with open(migration_path, 'r', encoding='utf-8') as f:
                        migration_sql = f.read()
                    
                    # Execute migration
                    cursor.executescript(migration_sql)
                    
                    # Record migration
                    cursor.execute(
                        "INSERT INTO migrations (filename) VALUES (?)",
                        (migration_file,)
                    )
                    
                    logger.info(f"Applied migration: {migration_file}")
    
    # User Management Methods
    def create_user(self, username: str, email: str = None) -> int:
        """Create a new user."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email) VALUES (?, ?)",
                (username, email)
            )
            return cursor.lastrowid
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by username."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # Addon Management Methods
    def register_addon(self, name: str, version: str) -> int:
        """Register an addon."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO addons (name, version) VALUES (?, ?)",
                (name, version)
            )
            return cursor.lastrowid
    
    def get_addon(self, name: str) -> Optional[Dict]:
        """Get addon by name."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM addons WHERE name = ?", (name,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_addons(self) -> List[Dict]:
        """Get all addons."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM addons ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
    
    def update_addon_config(self, name: str, config: Dict[str, Any]):
        """Update addon configuration."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE addons SET config = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                (json.dumps(config), name)
            )
    
    def get_addon_config(self, name: str) -> Dict[str, Any]:
        """Get addon configuration."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT config FROM addons WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row and row['config']:
                try:
                    return json.loads(row['config'])
                except json.JSONDecodeError:
                    return {}
            return {}
    
    # Settings Management Methods
    def get_setting(self, user_id: int, addon_name: str, key: str, default: Any = None) -> Any:
        """Get setting value."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT setting_value FROM settings WHERE user_id = ? AND addon_name = ? AND setting_key = ?",
                (user_id, addon_name, key)
            )
            row = cursor.fetchone()
            if row and row['setting_value']:
                try:
                    return json.loads(row['setting_value'])
                except json.JSONDecodeError:
                    return row['setting_value']
            return default
    
    def set_setting(self, user_id: int, addon_name: str, key: str, value: Any):
        """Set setting value."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Convert value to JSON if it's not a string
            if not isinstance(value, str):
                value = json.dumps(value)
            
            cursor.execute("""
                INSERT OR REPLACE INTO settings (user_id, addon_name, setting_key, setting_value)
                VALUES (?, ?, ?, ?)
            """, (user_id, addon_name, key, value))
    
    def get_all_settings(self, user_id: int, addon_name: str = None) -> Dict[str, Any]:
        """Get all settings for user or user+addon."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if addon_name:
                cursor.execute(
                    "SELECT setting_key, setting_value FROM settings WHERE user_id = ? AND addon_name = ?",
                    (user_id, addon_name)
                )
            else:
                cursor.execute(
                    "SELECT setting_key, setting_value FROM settings WHERE user_id = ?",
                    (user_id,)
                )
            
            settings = {}
            for row in cursor.fetchall():
                try:
                    settings[row['setting_key']] = json.loads(row['setting_value'])
                except json.JSONDecodeError:
                    settings[row['setting_key']] = row['setting_value']
            
            return settings
    
    # Farming Addon Specific Methods
    def get_farming_seeds_config(self, user_id: int) -> Dict[str, Dict]:
        """Get farming seeds configuration."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM farming_seeds")
            rows = cursor.fetchall()
            
            config = {}
            for row in rows:
                config[row['seed_type']] = {
                    'enabled': bool(row['enabled']),
                    'water_time': row['water_time'],
                    'fertilize_time': row['fertilize_time'],
                    'harvest_time': row['harvest_time']
                }
            
            return config
    
    def update_farming_seed_config(self, seed_type: str, config: Dict[str, Any]):
        """Update farming seed configuration."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO farming_seeds 
                (seed_type, enabled, water_time, fertilize_time, harvest_time)
                VALUES (?, ?, ?, ?, ?)
            """, (
                seed_type,
                int(config.get('enabled', False)),
                config.get('water_time', 30),
                config.get('fertilize_time', 60),
                config.get('harvest_time', 120)
            ))
    
    def get_user_inventory(self, user_id: int) -> Dict[str, Any]:
        """Get user's inventory."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM farming_inventory WHERE user_id = ?", (user_id,))
            rows = cursor.fetchall()
            
            inventory = {
                'seeds': {},
                'empty_bottles': 0,
                'water': 0,
                'fertilizer': 0
            }
            
            for row in rows:
                item_type = row['item_type']
                quantity = row['quantity']
                
                if item_type in ['empty_bottles', 'water', 'fertilizer']:
                    inventory[item_type] = quantity
                else:
                    inventory['seeds'][item_type] = quantity
            
            return inventory
    
    def update_inventory_item(self, user_id: int, item_type: str, quantity: int):
        """Update inventory item quantity."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO farming_inventory (user_id, item_type, quantity)
                VALUES (?, ?, ?)
            """, (user_id, item_type, quantity))
    
    def get_user_plants(self, user_id: int) -> Dict[str, Dict]:
        """Get user's active plants."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM farming_plants WHERE user_id = ?", (user_id,))
            rows = cursor.fetchall()
            
            plants = {}
            for row in rows:
                plants[row['plant_id']] = {
                    'type': row['plant_type'],
                    'status': row['status'],
                    'planted_time': row['planted_time'],
                    'last_watered': row['last_watered'],
                    'last_fertilized': row['last_fertilized'],
                    'next_action': row['next_action']
                }
            
            return plants
    
    def add_plant(self, user_id: int, plant_id: str, plant_type: str, instance_id: str = None):
        """Add new plant."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO farming_plants (user_id, plant_id, plant_type, instance_id)
                VALUES (?, ?, ?, ?)
            """, (user_id, plant_id, plant_type, instance_id))
    
    def update_plant(self, plant_id: str, updates: Dict[str, Any]):
        """Update plant information."""
        if not updates:
            return
        
        set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
        values = list(updates.values())
        values.append(plant_id)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE farming_plants SET {set_clause}
                WHERE plant_id = ?
            """, values)
    
    def remove_plant(self, plant_id: str):
        """Remove plant."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM farming_plants WHERE plant_id = ?", (plant_id,))
    
    def get_user_harvest_stats(self, user_id: int) -> Dict[str, Dict]:
        """Get user's harvest statistics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM farming_harvest_stats WHERE user_id = ?", (user_id,))
            rows = cursor.fetchall()
            
            stats = {}
            for row in rows:
                stats[row['plant_type']] = {
                    'total': row['total_harvested'],
                    'last_harvest': row['last_harvest'],
                    'average_yield': row['average_yield']
                }
            
            return stats
    
    def update_harvest_stats(self, user_id: int, plant_type: str):
        """Update harvest statistics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if stats exist
            cursor.execute(
                "SELECT * FROM farming_harvest_stats WHERE user_id = ? AND plant_type = ?",
                (user_id, plant_type)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Update existing stats
                cursor.execute("""
                    UPDATE farming_harvest_stats 
                    SET total_harvested = total_harvested + 1,
                        last_harvest = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND plant_type = ?
                """, (user_id, plant_type))
            else:
                # Insert new stats
                cursor.execute("""
                    INSERT INTO farming_harvest_stats (user_id, plant_type, total_harvested, last_harvest, average_yield)
                    VALUES (?, ?, 1, CURRENT_TIMESTAMP, 3.0)
                """, (user_id, plant_type))
    
    # Chat Events Methods
    def add_chat_event(self, user_id: int, event_type: str, event_data: str, instance_id: str = None):
        """Add chat event."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_events (user_id, event_type, event_data, instance_id)
                VALUES (?, ?, ?, ?)
            """, (user_id, event_type, event_data, instance_id))
    
    def get_unprocessed_chat_events(self, user_id: int) -> List[Dict]:
        """Get unprocessed chat events."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM chat_events 
                WHERE user_id = ? AND processed = 0 
                ORDER BY timestamp
            """, (user_id,))
            
            return [
                {
                    'event_id': row['event_id'],
                    'event_type': row['event_type'],
                    'event_data': row['event_data'],
                    'timestamp': row['timestamp'],
                    'instance_id': row['instance_id']
                }
                for row in cursor.fetchall()
            ]
    
    def mark_chat_event_processed(self, event_id: int):
        """Mark chat event as processed."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE chat_events SET processed = 1 WHERE event_id = ?", (event_id,))
    
    # Utility Methods
    def backup_database(self, backup_path: Path = None):
        """Create backup of database."""
        if not backup_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.db_path.parent.parent / "data" / "backups" / f"pglok_backup_{timestamp}.db"
        
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        
        import shutil
        shutil.copy2(self.db_path, backup_path)
        logger.info(f"Database backed up to {backup_path}")
        return backup_path
    
    def get_database_info(self) -> Dict[str, Any]:
        """Get database information."""
        info = {
            'database_path': str(self.db_path),
            'file_size': self.db_path.stat().st_size if self.db_path.exists() else 0,
            'tables': {}
        }
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get table counts
            tables = [
                'users', 'addons', 'farming_seeds', 'farming_inventory',
                'farming_plants', 'farming_harvest_stats', 'chat_events', 'settings'
            ]
            
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
                    info['tables'][table] = cursor.fetchone()['count']
                except sqlite3.OperationalError:
                    info['tables'][table] = 0
        
        return info

# Global database manager instance
_db_manager = None

def get_database_manager(db_path: Path = None) -> UnifiedDatabaseManager:
    """Get or create database manager instance."""
    global _db_manager
    
    if _db_manager is None:
        if db_path is None:
            # Default database path
            from pathlib import Path
            db_path = Path.home() / ".pglok" / "data" / "pglok.db"
        
        _db_manager = UnifiedDatabaseManager(db_path)
    
    return _db_manager
