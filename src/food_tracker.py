"""Food tracker module for managing eaten/uneaten food states."""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict


@dataclass
class FoodEntry:
    """Represents a single food entry with tracking state."""
    item_id: str
    name: str
    base_name: str
    descriptors: List[str]
    eaten: bool = False
    eaten_date: Optional[str] = None
    eaten_time: Optional[str] = None
    character_name: Optional[str] = None
    
    def mark_eaten(self, character_name: str = "Unknown"):
        """Mark this food as eaten."""
        self.eaten = True
        now = datetime.now()
        self.eaten_date = now.strftime("%Y-%m-%d")
        self.eaten_time = now.strftime("%H:%M:%S")
        self.character_name = character_name
    
    def mark_uneaten(self):
        """Mark this food as not eaten."""
        self.eaten = False
        self.eaten_date = None
        self.eaten_time = None
        self.character_name = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)


class FoodTracker:
    """Manages food tracking state - eaten/uneaten foods."""
    
    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize the food tracker.
        
        Args:
            data_dir: Directory to store tracking data. If None, uses default.
        """
        if data_dir is None:
            data_dir = Path(__file__).parent / 'data'
        
        self.data_dir = data_dir
        self.tracking_file = data_dir / 'food_tracking.json'
        self.foods: Dict[str, FoodEntry] = {}
        
        self._load_tracking_data()
    
    def _load_tracking_data(self):
        """Load existing tracking data from file."""
        if self.tracking_file.exists():
            try:
                with open(self.tracking_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item_id, entry_data in data.items():
                        self.foods[item_id] = FoodEntry(**entry_data)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Error loading tracking data: {e}")
                self.foods = {}
    
    def _save_tracking_data(self):
        """Save tracking data to file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = {item_id: entry.to_dict() for item_id, entry in self.foods.items()}
        with open(self.tracking_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def add_food(self, item_id: str, name: str, base_name: str, 
                 descriptors: List[str], eaten: bool = False) -> FoodEntry:
        """Add a food item to tracking.
        
        Args:
            item_id: Unique item identifier
            name: Full item name
            base_name: Name without descriptors
            descriptors: List of food descriptors
            eaten: Whether this food has been eaten
            
        Returns:
            The created FoodEntry
        """
        entry = FoodEntry(
            item_id=item_id,
            name=name,
            base_name=base_name,
            descriptors=descriptors,
            eaten=eaten
        )
        self.foods[item_id] = entry
        self._save_tracking_data()
        return entry
    
    def mark_eaten(self, item_id: str, character_name: str = "Unknown") -> bool:
        """Mark a food as eaten.
        
        Args:
            item_id: ID of the food to mark
            character_name: Name of character who ate it
            
        Returns:
            True if successful, False if food not found
        """
        if item_id in self.foods:
            self.foods[item_id].mark_eaten(character_name)
            self._save_tracking_data()
            return True
        return False
    
    def mark_uneaten(self, item_id: str) -> bool:
        """Mark a food as not eaten.
        
        Args:
            item_id: ID of the food to mark
            
        Returns:
            True if successful, False if food not found
        """
        if item_id in self.foods:
            self.foods[item_id].mark_uneaten()
            self._save_tracking_data()
            return True
        return False
    
    def get_eaten_foods(self) -> List[FoodEntry]:
        """Get all foods that have been eaten."""
        return [f for f in self.foods.values() if f.eaten]
    
    def get_uneaten_foods(self) -> List[FoodEntry]:
        """Get all foods that have not been eaten."""
        return [f for f in self.foods.values() if not f.eaten]
    
    def get_all_foods(self) -> List[FoodEntry]:
        """Get all tracked foods."""
        return list(self.foods.values())
    
    def get_food_by_id(self, item_id: str) -> Optional[FoodEntry]:
        """Get a specific food by ID."""
        return self.foods.get(item_id)
    
    def export_to_csv(self, output_path: Path, character_name: str = "Unknown") -> bool:
        """Export food tracking data to CSV.
        
        Args:
            output_path: Path to save the CSV file
            character_name: Character name to include in export
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # Write header
                writer.writerow([
                    'Item ID', 'Name', 'Base Name', 'Descriptors',
                    'Eaten', 'Date', 'Time', 'Character'
                ])
                
                # Write data
                for entry in self.foods.values():
                    writer.writerow([
                        entry.item_id,
                        entry.name,
                        entry.base_name,
                        ', '.join(entry.descriptors),
                        'Yes' if entry.eaten else 'No',
                        entry.eaten_date or '',
                        entry.eaten_time or '',
                        entry.character_name or character_name if entry.eaten else ''
                    ])
            return True
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            return False
    
    def import_food_list(self, foods_data: List[dict], clear_existing: bool = False):
        """Import a list of foods from the food parser.
        
        Args:
            foods_data: List of food dictionaries from FoodParser
            clear_existing: Whether to clear existing tracking data
        """
        if clear_existing:
            self.foods.clear()
        
        for food_data in foods_data:
            item_id = food_data.get('item_id')
            if item_id and item_id not in self.foods:
                self.add_food(
                    item_id=item_id,
                    name=food_data.get('name', ''),
                    base_name=food_data.get('base_name', ''),
                    descriptors=food_data.get('descriptors', [])
                )
        
        self._save_tracking_data()
    
    def get_statistics(self) -> dict:
        """Get statistics about food tracking."""
        total = len(self.foods)
        eaten = len(self.get_eaten_foods())
        uneaten = total - eaten
        
        return {
            'total': total,
            'eaten': eaten,
            'uneaten': uneaten,
            'percentage_eaten': (eaten / total * 100) if total > 0 else 0
        }
