"""Gourmand report parser for extracting eaten foods from skill reports."""
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Set, Optional


class GourmandReportParser:
    """Parser for Gourmand skill reports to extract eaten foods."""
    
    # Pattern to match report files: SkillReport_*Savetime*.txt
    REPORT_PATTERN = "SkillReport_*.txt"
    
    # Time window to consider reports "recent" (in minutes)
    RECENT_WINDOW_MINUTES = 5
    
    def __init__(self, books_dir: Path):
        """Initialize the parser.
        
        Args:
            books_dir: Path to Project Gorgon/Books directory
        """
        self.books_dir = books_dir
    
    def find_recent_reports(self) -> List[Path]:
        """Find recently saved skill reports.
        
        Returns:
            List of paths to recent report files
        """
        if not self.books_dir.exists():
            return []
        
        recent_reports = []
        cutoff_time = datetime.now() - timedelta(minutes=self.RECENT_WINDOW_MINUTES)
        
        # Find all SkillReport files
        for report_file in self.books_dir.glob(self.REPORT_PATTERN):
            if report_file.is_file():
                # Check modification time
                mtime = datetime.fromtimestamp(report_file.stat().st_mtime)
                if mtime > cutoff_time:
                    recent_reports.append((report_file, mtime))
        
        # Sort by modification time (most recent first)
        recent_reports.sort(key=lambda x: x[1], reverse=True)
        
        return [r[0] for r in recent_reports]
    
    def parse_report(self, report_path: Path) -> Set[str]:
        """Parse a skill report to find eaten foods.
        
        The Gourmand skill report typically lists foods in a format like:
        - "You have eaten: [Food Name]"
        - "Foods consumed:"
        - Or a list of food items
        
        Args:
            report_path: Path to the skill report file
            
        Returns:
            Set of food names found in the report
        """
        eaten_foods = set()
        
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (IOError, UnicodeDecodeError) as e:
            print(f"Error reading report {report_path}: {e}")
            return eaten_foods
        
        # Parse the content for food entries
        # Gourmand reports typically have sections with headers
        lines = content.split('\n')
        
        # Look for food-related sections
        in_food_section = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check for section headers that indicate food lists
            lower_line = line.lower()
            
            # Common headers in Gourmand reports
            if any(header in lower_line for header in [
                'foods eaten',
                'foods consumed',
                'foods you have eaten',
                'gourmand',
                'favorites',
                'least favorites'
            ]):
                in_food_section = True
                continue
            
            # End of section (new header or separator)
            if line.startswith('==') or line.startswith('--'):
                in_food_section = False
                continue
            
            # If in food section, extract food names
            if in_food_section:
                # Remove common prefixes/suffixes
                food_name = self._clean_food_name(line)
                if food_name:
                    eaten_foods.add(food_name)
            
            # Also look for "You have eaten: Food Name" patterns anywhere
            eaten_match = re.search(r'you have eaten[:\s]+(.+)', lower_line)
            if eaten_match:
                food_name = self._clean_food_name(eaten_match.group(1))
                if food_name:
                    eaten_foods.add(food_name)
            
            # Look for numbered or bulleted list items that might be foods
            list_match = re.search(r'^[\s]*[\d\*\-\+\.\)]*[\s]*(.+)', line)
            if list_match:
                potential_food = self._clean_food_name(list_match.group(1))
                # Add if it looks like a food (has food-related keywords)
                if potential_food and self._looks_like_food(potential_food):
                    eaten_foods.add(potential_food)
        
        return eaten_foods
    
    def _clean_food_name(self, name: str) -> str:
        """Clean up a food name from the report.
        
        Args:
            name: Raw food name from report
            
        Returns:
            Cleaned food name
        """
        # Remove leading/trailing punctuation and whitespace
        name = name.strip().strip(':-–—•*')
        
        # Remove quantity indicators (e.g., "x5", "(3)", "[10]")
        name = re.sub(r'\s*[×xX]\s*\d+', '', name)
        name = re.sub(r'\s*[\(\[]\s*\d+\s*[\)\]]', '', name)
        
        # Remove notes in parentheses
        name = re.sub(r'\s*\([^)]*\)', '', name)
        
        # Clean up extra whitespace
        name = ' '.join(name.split())
        
        return name.strip()
    
    def _looks_like_food(self, name: str) -> bool:
        """Check if a name looks like a food item.
        
        Args:
            name: Name to check
            
        Returns:
            True if it appears to be a food
        """
        # Common food keywords
        food_keywords = [
            'stew', 'soup', 'bread', 'cheese', 'meat', 'egg', 'pie', 'cake',
            'fruit', 'fish', 'steak', 'roast', 'jerky', 'wine', 'ale', 'beer',
            'sushi', 'kebab', 'sausage', 'bacon', 'ham', 'muffin', 'cookie',
            'salad', 'potato', 'carrot', 'apple', 'mushroom', 'nut', 'berry',
            'sandwich', 'pizza', 'pasta', 'rice', 'curry', 'stew', 'soup',
            'juice', 'milk', 'honey', 'jam', 'syrup', 'sauce', 'grilled',
            'fried', 'baked', 'roasted', 'boiled', 'barbecue', 'bbq', 'smoked'
        ]
        
        name_lower = name.lower()
        return any(kw in name_lower for kw in food_keywords)
    
    def get_eaten_foods_from_recent_reports(self) -> Set[str]:
        """Get all eaten foods from recent reports.
        
        Returns:
            Set of all food names found in recent reports
        """
        all_foods = set()
        
        recent_reports = self.find_recent_reports()
        for report in recent_reports:
            foods = self.parse_report(report)
            all_foods.update(foods)
        
        return all_foods
