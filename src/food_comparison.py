"""Food Comparison UI window for tracking eaten/uneaten foods."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import threading

from src.food_tracker import FoodTracker, FoodEntry
from src.food_parser import parse_foods, clear_food_cache


class FoodComparisonWindow:
    """Window for comparing and tracking foods."""
    
    def __init__(self, parent: tk.Tk, character_name: str = "Unknown"):
        """Initialize the food comparison window.
        
        Args:
            parent: Parent Tk window
            character_name: Current character name for tracking
        """
        self.parent = parent
        self.character_name = character_name
        
        # Create window
        self.window = tk.Toplevel(parent)
        self.window.title("Food Comparison & Tracking")
        self.window.geometry("900x600")
        self.window.minsize(700, 400)
        
        # Initialize food tracker and load data
        self.tracker = FoodTracker()
        self._load_foods_from_parser()
        
        # Build UI
        self._build_ui()
        
        # Initial refresh
        self.refresh_all_tabs()
    
    def _load_foods_from_parser(self):
        """Load foods from the food parser into the tracker."""
        parser = parse_foods()
        foods_data = [f.__dict__ for f in parser.get_all_foods()]
        self.tracker.import_food_list(foods_data)
    
    def _build_ui(self):
        """Build the user interface."""
        # Main frame
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill="both", expand=True)
        
        # Title and stats
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(
            header_frame, 
            text="Food Comparison & Tracking", 
            font=('Helvetica', 14, 'bold')
        ).pack(side="left")
        
        self.stats_label = ttk.Label(header_frame, text="")
        self.stats_label.pack(side="right")
        
        # Notebook for tabs
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill="both", expand=True, pady=(0, 10))
        
        # All Foods tab
        self.all_frame = self._create_food_tab("All Foods")
        self.notebook.add(self.all_frame, text="All Foods")
        
        # Eaten Foods tab
        self.eaten_frame = self._create_food_tab("Eaten")
        self.notebook.add(self.eaten_frame, text="Eaten")
        
        # Uneaten Foods tab
        self.uneaten_frame = self._create_food_tab("Uneaten")
        self.notebook.add(self.uneaten_frame, text="Uneaten")
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Button(
            button_frame, 
            text="Mark Selected as Eaten", 
            command=self._mark_selected_eaten
        ).pack(side="left", padx=(0, 5))
        
        ttk.Button(
            button_frame, 
            text="Mark Selected as Uneaten", 
            command=self._mark_selected_uneaten
        ).pack(side="left", padx=(0, 5))
        
        ttk.Button(
            button_frame,
            text="Import Gourmand Report",
            command=self._import_gourmand_report
        ).pack(side="left", padx=(0, 5))
        
        ttk.Button(
            button_frame, 
            text="Export to CSV", 
            command=self._export_csv
        ).pack(side="right")
        
        ttk.Button(
            button_frame, 
            text="Refresh", 
            command=self._on_refresh_clicked
        ).pack(side="right", padx=(0, 5))
    
    def _create_food_tab(self, tab_name: str) -> ttk.Frame:
        """Create a tab with a treeview for displaying foods.
        
        Args:
            tab_name: Name of the tab
            
        Returns:
            The created frame
        """
        frame = ttk.Frame(self.notebook, padding="5")
        
        # Search frame
        search_frame = ttk.Frame(frame)
        search_frame.pack(fill="x", pady=(0, 5))
        
        ttk.Label(search_frame, text="Search:").pack(side="left")
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var, width=30)
        search_entry.pack(side="left", padx=(5, 0))
        
        # Treeview with scrollbar
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        
        columns = ('name', 'base_name', 'descriptors', 'status', 'date', 'time')
        tree = ttk.Treeview(
            tree_frame, 
            columns=columns,
            show='headings',
            selectmode='extended'
        )
        
        # Define column headings
        tree.heading('name', text='Name')
        tree.heading('base_name', text='Base Name')
        tree.heading('descriptors', text='Descriptors')
        tree.heading('status', text='Status')
        tree.heading('date', text='Date Eaten')
        tree.heading('time', text='Time Eaten')
        
        # Set column widths
        tree.column('name', width=200)
        tree.column('base_name', width=150)
        tree.column('descriptors', width=120)
        tree.column('status', width=60)
        tree.column('date', width=90)
        tree.column('time', width=80)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Store references
        if tab_name == "All Foods":
            self.all_tree = tree
            self.all_search_var = search_var
        elif tab_name == "Eaten":
            self.eaten_tree = tree
            self.eaten_search_var = search_var
        else:
            self.uneaten_tree = tree
            self.uneaten_search_var = search_var
        
        # Bind search
        search_var.trace('w', lambda *args, t=tree, v=search_var: self._filter_tree(t, v.get()))
        
        return frame
    
    def _filter_tree(self, tree: ttk.Treeview, search_term: str):
        """Filter tree items based on search term."""
        search_lower = search_term.lower()
        
        for item in tree.get_children():
            values = tree.item(item, 'values')
            # Search in name and base_name
            if any(search_lower in str(v).lower() for v in values[:2]):
                tree.reattach(item, '', 'end')
            else:
                tree.detach(item)
    
    def _populate_tree(self, tree: ttk.Treeview, foods: List[FoodEntry]):
        """Populate a treeview with food entries.
        
        Args:
            tree: Treeview to populate
            foods: List of food entries
        """
        # Clear existing
        for item in tree.get_children():
            tree.delete(item)
        
        # Add items
        for food in foods:
            status = "Eaten" if food.eaten else "Uneaten"
            tree.insert('', 'end', iid=food.item_id, values=(
                food.name,
                food.base_name,
                ', '.join(food.descriptors),
                status,
                food.eaten_date or '',
                food.eaten_time or ''
            ))
    
    def refresh_all_tabs(self):
        """Refresh all tabs with current data."""
        # All foods
        all_foods = self.tracker.get_all_foods()
        self._populate_tree(self.all_tree, all_foods)
        
        # Eaten foods
        eaten_foods = self.tracker.get_eaten_foods()
        self._populate_tree(self.eaten_tree, eaten_foods)
        
        # Uneaten foods
        uneaten_foods = self.tracker.get_uneaten_foods()
        self._populate_tree(self.uneaten_tree, uneaten_foods)
        
        # Update stats
        stats = self.tracker.get_statistics()
        self.stats_label.config(
            text=f"Total: {stats['total']} | Eaten: {stats['eaten']} | Uneaten: {stats['uneaten']}"
        )
    
    def _on_refresh_clicked(self):
        """Handle Refresh button - clear cache and re-parse from JSON."""
        # Clear the food cache
        clear_food_cache()
        
        # Reload foods from JSON (no cache)
        self._load_foods_from_parser(refresh=True)
        
        # Refresh display
        self.refresh_all_tabs()
        
        messagebox.showinfo("Refresh Complete", "Food list refreshed from items.json")
    
    def _load_foods_from_parser(self, refresh: bool = False):
        """Load foods from the food parser into the tracker.
        
        Args:
            refresh: If True, force re-parse from JSON instead of using cache
        """
        parser = parse_foods(refresh=refresh)
        foods_data = [f.__dict__ for f in parser.get_all_foods()]
        self.tracker.import_food_list(foods_data, clear_existing=True)
    
    def _get_selected_items(self) -> List[str]:
        """Get currently selected item IDs from the active tab."""
        current_tab = self.notebook.index(self.notebook.select())
        
        if current_tab == 0:  # All Foods
            return list(self.all_tree.selection())
        elif current_tab == 1:  # Eaten
            return list(self.eaten_tree.selection())
        else:  # Uneaten
            return list(self.uneaten_tree.selection())
    
    def _mark_selected_eaten(self):
        """Mark selected items as eaten."""
        selected = self._get_selected_items()
        if not selected:
            messagebox.showwarning("No Selection", "Please select items to mark as eaten.")
            return
        
        for item_id in selected:
            self.tracker.mark_eaten(item_id, self.character_name)
        
        self.refresh_all_tabs()
        messagebox.showinfo("Success", f"Marked {len(selected)} items as eaten.")
    
    def _mark_selected_uneaten(self):
        """Mark selected items as uneaten."""
        selected = self._get_selected_items()
        if not selected:
            messagebox.showwarning("No Selection", "Please select items to mark as uneaten.")
            return
        
        for item_id in selected:
            self.tracker.mark_uneaten(item_id)
        
        self.refresh_all_tabs()
        messagebox.showinfo("Success", f"Marked {len(selected)} items as uneaten.")
    
    def _export_csv(self):
        """Export food tracking data to CSV."""
        # Default filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"food_tracking_{self.character_name}_{timestamp}.csv"
        
        # Ask for save location
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_name
        )
        
        if not file_path:
            return
        
        # Export
        if self.tracker.export_to_csv(Path(file_path), self.character_name):
            messagebox.showinfo("Export Successful", f"Food tracking data exported to:\n{file_path}")
        else:
            messagebox.showerror("Export Failed", "Failed to export food tracking data.")
    
    def focus(self):
        """Bring window to focus."""
        self.window.lift()
        self.window.focus_force()
    
    def _import_gourmand_report(self):
        """Show dialog to import gourmand report and watch for new files."""
        # Show instructions dialog
        self._show_gourmand_instructions()
    
    def _show_gourmand_instructions(self):
        """Show instructions dialog for saving gourmand report."""
        dialog = tk.Toplevel(self.window)
        dialog.title("Import Gourmand Report")
        dialog.geometry("500x350")
        dialog.transient(self.window)
        dialog.grab_set()
        
        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (dialog.winfo_screenheight() // 2) - (350 // 2)
        dialog.geometry(f"500x350+{x}+{y}")
        
        # Main frame
        frame = ttk.Frame(dialog, padding="20")
        frame.pack(fill="both", expand=True)
        
        # Instructions
        ttk.Label(
            frame,
            text="Import Gourmand Report",
            font=('Helvetica', 14, 'bold')
        ).pack(pady=(0, 15))
        
        instructions = """
To import your eaten foods:

1. In Project Gorgon, open your Gourmand skill panel
2. Click the "Save Report" button
3. Save the report to: Project Gorgon/Books/

The file will be named: SkillReport_*Savetime*.txt

This tool will automatically detect the saved report
and mark all foods you've eaten.
        """
        
        ttk.Label(
            frame,
            text=instructions,
            justify="left",
            wraplength=440
        ).pack(pady=(0, 15))
        
        # Status label
        self.import_status_var = tk.StringVar(value="Waiting for report...")
        status_label = ttk.Label(
            frame,
            textvariable=self.import_status_var,
            font=('Helvetica', 10, 'italic')
        )
        status_label.pack(pady=(0, 15))
        
        # Progress bar
        self.import_progress = ttk.Progressbar(frame, mode="indeterminate", length=400)
        self.import_progress.pack(pady=(0, 15))
        self.import_progress.start(10)
        
        # Button frame
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Button(
            btn_frame,
            text="Cancel",
            command=dialog.destroy
        ).pack(side="right", padx=(5, 0))
        
        # Start watching for files
        self._start_file_watch(dialog)
    
    def _start_file_watch(self, dialog):
        """Start watching for new gourmand report files."""
        import threading
        import time
        
        def watch_loop():
            """Background thread to watch for new files."""
            from datetime import datetime, timedelta
            
            # Find the Project Gorgon Books directory (in background thread)
            books_dir = self._get_books_directory()
            if not books_dir:
                self.window.after(0, lambda: self._watch_error(dialog, "Could not find Project Gorgon/Books directory"))
                return
            
            # Update UI with found directory
            self.window.after(0, lambda: self.import_status_var.set(f"Watching: {books_dir}"))
            
            # Track files we've seen
            seen_files = set()
            
            # Check for existing files first
            for f in books_dir.glob("SkillReport_*.txt"):
                seen_files.add(f.name)
            
            max_attempts = 120  # Watch for up to 2 minutes
            attempts = 0
            
            while attempts < max_attempts and dialog.winfo_exists():
                try:
                    # Check for new files
                    for report_file in books_dir.glob("SkillReport_*.txt"):
                        if report_file.name not in seen_files:
                            # New file detected!
                            mtime = datetime.fromtimestamp(report_file.stat().st_mtime)
                            age_minutes = (datetime.now() - mtime).total_seconds() / 60
                            
                            # If file is very recent (saved in last 5 minutes)
                            if age_minutes < 5:
                                # Update UI and process
                                self.window.after(0, lambda: self._process_report(report_file, dialog))
                                return
                    
                    attempts += 1
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Error watching files: {e}")
                    time.sleep(1)
            
            # Timeout - stop watching
            if dialog.winfo_exists():
                self.window.after(0, lambda: self._watch_timeout(dialog))
        
        # Start watching in background thread
        threading.Thread(target=watch_loop, daemon=True).start()
    
    def _watch_error(self, dialog, error_msg):
        """Handle watch error on UI thread."""
        self.import_status_var.set(f"Error: {error_msg}")
        self.import_progress.stop()
        
        # Ask user to browse for directory
        response = messagebox.askyesno(
            "Books Directory Not Found",
            "Could not auto-detect the Project Gorgon/Books directory.\n\n"
            "Would you like to browse for it manually?\n\n"
            "(Look in your Project Gorgon game folder for a 'Books' subfolder)",
            parent=dialog
        )
        
        if response:
            # Open directory browser
            selected_dir = filedialog.askdirectory(
                title="Select Project Gorgon/Books Directory",
                parent=dialog
            )
            if selected_dir:
                books_path = Path(selected_dir)
                # Verify it contains SkillReport files
                if any(books_path.glob("SkillReport_*.txt")):
                    self.import_status_var.set(f"Watching: {books_path}")
                    self.import_progress.start(10)
                    # Continue watching with selected directory
                    self._continue_watch_with_path(dialog, books_path)
                else:
                    messagebox.showwarning(
                        "Invalid Directory",
                        f"Selected directory does not contain any SkillReport_*.txt files.\n"
                        f"Please select the correct Books directory.",
                        parent=dialog
                    )
        else:
            dialog.destroy()
    
    def _continue_watch_with_path(self, dialog, books_path: Path):
        """Continue file watching with a manually selected path."""
        import threading
        import time
        from datetime import datetime
        
        def watch_loop():
            seen_files = set()
            
            # Check for existing files first
            for f in books_path.glob("SkillReport_*.txt"):
                seen_files.add(f.name)
            
            max_attempts = 120
            attempts = 0
            
            while attempts < max_attempts and dialog.winfo_exists():
                try:
                    for report_file in books_path.glob("SkillReport_*.txt"):
                        if report_file.name not in seen_files:
                            mtime = datetime.fromtimestamp(report_file.stat().st_mtime)
                            age_minutes = (datetime.now() - mtime).total_seconds() / 60
                            
                            if age_minutes < 5:
                                self.window.after(0, lambda: self._process_report(report_file, dialog))
                                return
                    
                    attempts += 1
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Error watching files: {e}")
                    time.sleep(1)
            
            if dialog.winfo_exists():
                self.window.after(0, lambda: self._watch_timeout(dialog))
        
        threading.Thread(target=watch_loop, daemon=True).start()
    
    def _get_books_directory(self) -> Optional[Path]:
        """Get the Project Gorgon Books directory."""
        import os
        home = Path.home()
        
        # Try common locations - expanded list
        possible_paths = [
            # Linux/macOS home directory
            home / "Project Gorgon" / "Books",
            
            # Windows common paths
            home / "Documents" / "Project Gorgon" / "Books",
            home / "My Games" / "Project Gorgon" / "Books",
            Path("C:/") / "Users" / os.environ.get("USERNAME", "") / "Project Gorgon" / "Books",
            Path("C:/") / "Users" / os.environ.get("USERNAME", "") / "Documents" / "Project Gorgon" / "Books",
            
            # AppData locations (Windows)
            home / "AppData" / "Local" / "Project Gorgon" / "Books",
            home / "AppData" / "LocalLow" / "Project Gorgon" / "Books",
            home / "AppData" / "Roaming" / "Project Gorgon" / "Books",
            
            # Steam paths
            Path("C:/Program Files (x86)/Steam/steamapps/common/Project Gorgon/Books"),
            Path("C:/Program Files/Steam/steamapps/common/Project Gorgon/Books"),
            home / ".steam" / "steam" / "steamapps" / "common" / "Project Gorgon" / "Books",
            
            # macOS
            home / "Library" / "Application Support" / "Project Gorgon" / "Books",
            
            # Linux
            home / ".config" / "Project Gorgon" / "Books",
            home / ".local" / "share" / "Project Gorgon" / "Books",
            
            # Just the Project Gorgon folder (maybe Books is inside)
            home / "Project Gorgon",
            home / "Documents" / "Project Gorgon",
        ]
        
        # Also check environment variable
        if "PG_BASE" in os.environ:
            env_path = Path(os.environ["PG_BASE"])
            possible_paths.insert(0, env_path / "Books")
            possible_paths.insert(1, env_path)  # Maybe Books is inside
        
        # Check each path
        for path in possible_paths:
            if path.exists():
                # If this is the Books directory itself, return it
                if path.name == "Books":
                    return path
                # If this is Project Gorgon directory, look for Books inside
                books_subdir = path / "Books"
                if books_subdir.exists():
                    return books_subdir
        
        return None
    
    def _process_report(self, report_file: Path, dialog):
        """Process the detected gourmand report."""
        self.import_status_var.set(f"Processing: {report_file.name}")
        self.import_progress.stop()
        
        try:
            # Import gourmand parser with proper path
            from src.gourmand_parser import GourmandReportParser
            
            # Parse the report
            parser = GourmandReportParser(report_file.parent)
            eaten_foods = parser.parse_report(report_file)
            
            if eaten_foods:
                # Match foods by name and mark as eaten
                matched_count = self._apply_eaten_foods(eaten_foods)
                
                message = f"Found {len(eaten_foods)} foods in report.\nMatched and marked {matched_count} as eaten."
                messagebox.showinfo("Import Complete", message, parent=dialog)
                
                # Refresh the display
                self.refresh_all_tabs()
            else:
                messagebox.showwarning(
                    "No Foods Found",
                    "Could not find any foods in the report.\nMake sure you saved the Gourmand skill report.",
                    parent=dialog
                )
            
            dialog.destroy()
            
        except Exception as e:
            messagebox.showerror(
                "Import Error",
                f"Error processing report: {e}",
                parent=dialog
            )
            dialog.destroy()
    
    def _apply_eaten_foods(self, eaten_foods: set) -> int:
        """Apply eaten status to matching foods in tracker.
        
        Args:
            eaten_foods: Set of food names from report
            
        Returns:
            Number of foods matched and marked as eaten
        """
        matched = 0
        
        for food_entry in self.tracker.get_all_foods():
            # Check if this food's name or base_name matches any eaten food
            food_names = [
                food_entry.name.lower(),
                food_entry.base_name.lower()
            ]
            
            for eaten_name in eaten_foods:
                eaten_lower = eaten_name.lower()
                
                # Exact match
                if eaten_lower in food_names:
                    self.tracker.mark_eaten(food_entry.item_id, self.character_name)
                    matched += 1
                    break
                
                # Partial match - check if eaten name is contained in food name
                for fn in food_names:
                    if eaten_lower in fn or fn in eaten_lower:
                        # More careful matching for partials
                        if len(eaten_lower) > 5:  # Only match substantial names
                            self.tracker.mark_eaten(food_entry.item_id, self.character_name)
                            matched += 1
                            break
        
        return matched
    
    def _watch_timeout(self, dialog):
        """Handle watch timeout."""
        self.import_progress.stop()
        self.import_status_var.set("Timed out - no new report detected")
        
        response = messagebox.askyesno(
            "No Report Found",
            "No new gourmand report was detected in the last 2 minutes.\n\n"
            "Did you save the report to Project Gorgon/Books/?\n\n"
            "Click Yes to continue waiting, No to cancel.",
            parent=dialog
        )
        
        if response:
            # Restart watching
            self.import_status_var.set("Waiting for report...")
            self.import_progress.start(10)
            self._start_file_watch(dialog)
        else:
            dialog.destroy()


def open_food_comparison(parent: tk.Tk, character_name: str = "Unknown") -> FoodComparisonWindow:
    """Open the food comparison window.
    
    Args:
        parent: Parent Tk window
        character_name: Current character name
        
    Returns:
        The created FoodComparisonWindow instance
    """
    return FoodComparisonWindow(parent, character_name)
