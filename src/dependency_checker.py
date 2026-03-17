"""
Dependency Checker for PGLOK
"""

import subprocess
import sys
import importlib
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import List, Dict, Tuple

class DependencyChecker:
    """Handles dependency checking and installation for PGLOK."""
    
    def __init__(self, parent_app):
        self.parent_app = parent_app
        self.colors = self._get_colors()
        
        # Define required dependencies
        self.required_dependencies = {
            "requests": {
                "version": ">=2.25.0",
                "description": "HTTP library for web requests",
                "optional": False
            },
            "psutil": {
                "version": ">=5.8.0",
                "description": "System and process utilities",
                "optional": False
            }
        }
        
        # Scan addons for additional dependencies
        self.addon_dependencies = self._scan_addon_dependencies()
    
    def _scan_addon_dependencies(self) -> Dict[str, Dict]:
        """Scan addons for additional dependencies."""
        addon_deps = {}
        
        try:
            # Get addons directory - fix path calculation
            from pathlib import Path
            current_file = Path(__file__)
            project_root = current_file.parent.parent
            addons_dir = project_root / "addons"
            
            if not addons_dir.exists():
                return addon_deps
            
            # Scan each addon directory
            for addon_dir in addons_dir.iterdir():
                if addon_dir.is_dir():
                    addon_name = addon_dir.name
                    
                    # Check for addon.json manifest
                    manifest_file = addon_dir / "addon.json"
                    if manifest_file.exists():
                        try:
                            import json
                            with open(manifest_file, 'r', encoding='utf-8') as f:
                                manifest = json.load(f)
                            
                            # Check for dependencies in manifest
                            if 'dependencies' in manifest:
                                for dep_info in manifest['dependencies']:
                                    if isinstance(dep_info, str):
                                        # Simple string: "pynput>=1.7.6"
                                        if '>=' in dep_info:
                                            pkg, version = dep_info.split('>=')
                                        elif '==' in dep_info:
                                            pkg, version = dep_info.split('==')
                                        else:
                                            pkg, version = dep_info, ">=0.0.0"
                                    elif isinstance(dep_info, dict):
                                        # Dict format: {"name": "pynput", "version": ">=1.7.6"}
                                        pkg = dep_info.get('name', '')
                                        version = dep_info.get('version', '>=0.0.0')
                                    else:
                                        continue
                                    
                                    # Add to addon dependencies
                                    if pkg not in addon_deps:
                                        addon_deps[pkg] = {
                                            "version": version,
                                            "description": f"Required by {addon_name} addon",
                                            "optional": False,
                                            "addon_specific": addon_name
                                        }
                                    else:
                                        # Update description if multiple addons use it
                                        existing = addon_deps[pkg]
                                        if existing["addon_specific"] != addon_name:
                                            existing["description"] = f"Required by {existing['addon_specific']} and {addon_name} addons"
                                            existing["addon_specific"] = f"{existing['addon_specific']}, {addon_name}"
                            
                            # Also check requirements.txt if it exists
                            requirements_file = addon_dir / "requirements.txt"
                            if requirements_file.exists():
                                with open(requirements_file, 'r', encoding='utf-8') as f:
                                    for line in f:
                                        line = line.strip()
                                        if line and not line.startswith('#') and not line.startswith('-'):
                                            # Parse requirement
                                            if '>=' in line:
                                                pkg, version = line.split('>=')
                                            elif '==' in line:
                                                pkg, version = line.split('==')
                                            else:
                                                pkg, version = line, ">=0.0.0"
                                            
                                            # Clean up package name
                                            pkg = pkg.strip()
                                            version = version.strip()
                                            
                                            if pkg not in addon_deps:
                                                addon_deps[pkg] = {
                                                    "version": version,
                                                    "description": f"Required by {addon_name} addon",
                                                    "optional": False,
                                                    "addon_specific": addon_name
                                                }
                        
                        except Exception as e:
                            print(f"Warning: Failed to parse manifest for {addon_name}: {e}")
                            continue
                    
                    # Check for known addon-specific dependencies
                    # Special handling for known addons
                    if addon_name.lower() == "bambam":
                        if "pynput" not in addon_deps:
                            addon_deps["pynput"] = {
                                "version": ">=1.7.6",
                                "description": "Keyboard and mouse input capture (for BamBam macros)",
                                "optional": True,
                                "addon_specific": "BamBam"
                            }
        
        except Exception as e:
            print(f"Warning: Failed to scan addon dependencies: {e}")
        
        return addon_deps
    
    def _get_colors(self):
        """Get PGLOK theme colors."""
        try:
            from src.config.ui_theme import UI_COLORS
            return UI_COLORS
        except:
            # Fallback colors
            return {
                "bg": "#060507",
                "fg": "#ddd6c8",
                "primary": "#8d321e",
                "secondary": "#3a231d",
                "entry_bg": "#140f0f",
                "entry_fg": "#ddd6c8",
                "panel_bg": "#140f0e",
                "card_bg": "#1e1413",
                "muted_text": "#baa98d"
            }
    
    def check_dependencies(self) -> Tuple[List[str], List[str]]:
        """Check which dependencies are installed and which are missing."""
        installed = []
        missing = []
        
        # Combine core and addon dependencies
        all_dependencies = {**self.required_dependencies, **self.addon_dependencies}
        
        for package, info in all_dependencies.items():
            try:
                # Try to import the package
                importlib.import_module(package)
                installed.append(package)
            except ImportError:
                missing.append(package)
        
        return installed, missing
    
    def get_dependency_status(self) -> Dict[str, Dict]:
        """Get detailed status of all dependencies."""
        status = {}
        
        # Combine core and addon dependencies
        all_dependencies = {**self.required_dependencies, **self.addon_dependencies}
        
        for package, info in all_dependencies.items():
            try:
                # Try to import and get version
                module = importlib.import_module(package)
                version = getattr(module, '__version__', 'Unknown')
                
                status[package] = {
                    "installed": True,
                    "version": version,
                    "description": info["description"],
                    "optional": info["optional"],
                    "addon_specific": info.get("addon_specific", ""),
                    "required_version": info["version"]
                }
            except ImportError:
                status[package] = {
                    "installed": False,
                    "version": None,
                    "description": info["description"],
                    "optional": info["optional"],
                    "addon_specific": info.get("addon_specific", ""),
                    "required_version": info["version"]
                }
        
        return status
    
    def install_dependencies(self, packages: List[str], progress_callback=None) -> bool:
        """Install specified dependencies."""
        try:
            # Combine core and addon dependencies for version lookup
            all_dependencies = {**self.required_dependencies, **self.addon_dependencies}
            
            for i, package in enumerate(packages):
                if progress_callback:
                    progress_callback(f"Installing {package}...", (i + 1) / len(packages))
                
                # Get version requirement from combined dependencies
                if package in all_dependencies:
                    version_spec = all_dependencies[package]["version"]
                else:
                    version_spec = ">=0.0.0"  # Default if not found
                
                install_spec = f"{package}{version_spec}"
                
                try:
                    # Install the package
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", install_spec],
                        capture_output=True,
                        text=True,
                        timeout=300  # 5 minute timeout per package
                    )
                    
                    if result.returncode != 0:
                        if progress_callback:
                            progress_callback(f"Failed to install {package}: {result.stderr}", 0)
                        print(f"Installation failed for {package}: {result.stderr}")
                        return False
                    
                    if progress_callback:
                        progress_callback(f"Successfully installed {package}", (i + 1) / len(packages))
                
                except subprocess.TimeoutExpired:
                    if progress_callback:
                        progress_callback(f"Timeout installing {package}", 0)
                    print(f"Timeout installing {package}")
                    return False
                
                except Exception as e:
                    if progress_callback:
                        progress_callback(f"Error installing {package}: {e}", 0)
                    print(f"Error installing {package}: {e}")
                    return False
            
            return True
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"Installation error: {e}", 0)
            print(f"Installation error: {e}")
            return False
    
    def show_dependency_checker(self):
        """Show the dependency checker window."""
        try:
            # Check if parent app and root exist
            if not self.parent_app or not hasattr(self.parent_app, 'root') or not self.parent_app.root:
                print("Error: Parent app or root window not available")
                messagebox.showerror("Error", "PGLOK application window not available")
                return None
            
            # Check if root window still exists
            try:
                self.parent_app.root.update()
            except tk.TclError:
                print("Error: Root window no longer exists")
                messagebox.showerror("Error", "PGLOK application window is no longer available")
                return None
            
            # Create modal window using app helper so theme and geometry persist
            if hasattr(self.parent_app, 'create_themed_toplevel'):
                checker_window = self.parent_app.create_themed_toplevel("dependency_checker", "Dependencies")
            else:
                checker_window = tk.Toplevel(self.parent_app.root)
                try:
                    from src.config.window_state import setup_window
                    setup_window(checker_window, "dependency_checker", min_w=700, min_h=500)
                except Exception:
                    pass

            # Make modal
            try:
                checker_window.transient(self.parent_app.root)
                checker_window.grab_set()
            except Exception:
                pass

            # Main frame
            main_frame = ttk.Frame(checker_window, style="App.Card.TFrame", padding=20)
            main_frame.pack(fill="both", expand=True)
            
            # Title
            title_label = ttk.Label(main_frame, text="Dependency Status", 
                                  style="App.Title.TLabel")
            title_label.pack(pady=(0, 20))
            
            # Status display
            status_frame = ttk.LabelFrame(main_frame, text="Package Status", 
                                          style="App.Panel.TFrame", padding=10)
            status_frame.pack(fill="both", expand=True, pady=(0, 20))
            
            # Create treeview for dependency status
            columns = ("Package", "Version", "Status", "Description", "Used By")
            tree = ttk.Treeview(status_frame, columns=columns, show="headings", height=10)
            
            # Configure columns
            tree.column("Package", width=100)
            tree.column("Version", width=100)
            tree.column("Status", width=80)
            tree.column("Description", width=250)
            tree.column("Used By", width=100)
            
            # Configure headings
            tree.heading("Package", text="Package")
            tree.heading("Version", text="Version")
            tree.heading("Status", text="Status")
            tree.heading("Description", text="Description")
            tree.heading("Used By", text="Used By")
            
            # Add dependency status
            status = self.get_dependency_status()
            missing_packages = []
            
            for package, info in status.items():
                status_text = "✓ Installed" if info["installed"] else "✗ Missing"
                version_text = info["version"] if info["version"] else "N/A"
                used_by = info["addon_specific"] if info["addon_specific"] else "PGLOK Core"
                
                tag = "installed" if info["installed"] else "missing"
                tree.insert("", "end", values=(
                    package,
                    version_text,
                    status_text,
                    info["description"],
                    used_by
                ), tags=(tag,))
                
                if not info["installed"] and not info["optional"]:
                    missing_packages.append(package)
            
            # Configure tags for coloring
            tree.tag_configure("installed", foreground="#107c10")
            tree.tag_configure("missing", foreground="#d83b01")
            
            tree.pack(fill="both", expand=True)
            
            # Progress frame
            progress_frame = ttk.Frame(main_frame, style="App.TFrame")
            progress_frame.pack(fill="x", pady=(0, 20))
            
            self.progress_var = tk.DoubleVar()
            self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, 
                                                mode="determinate", style="App.Horizontal.TProgressbar")
            
            self.status_label = ttk.Label(progress_frame, text="Ready", style="App.Status.TLabel")
            self.status_label.pack(fill="x", pady=(0, 5))
            
            # Action buttons
            button_frame = ttk.Frame(main_frame, style="App.TFrame")
            button_frame.pack(fill="x")
            
            def check_dependencies():
                """Refresh dependency status."""
                try:
                    status = self.get_dependency_status()
                    
                    # Clear existing items
                    for item in tree.get_children():
                        tree.delete(item)
                    
                    # Re-add items with updated status
                    for package, info in status.items():
                        status_text = "✓ Installed" if info["installed"] else "✗ Missing"
                        version_text = info["version"] if info["version"] else "N/A"
                        used_by = info["addon_specific"] if info["addon_specific"] else "PGLOK Core"
                        
                        tag = "installed" if info["installed"] else "missing"
                        tree.insert("", "end", values=(
                            package,
                            version_text,
                            status_text,
                            info["description"],
                            used_by
                        ), tags=(tag,))
                    
                    self.status_label.configure(text="Dependencies checked")
                except Exception as e:
                    print(f"Error checking dependencies: {e}")
                    self.status_label.configure(text=f"Error checking dependencies: {e}")
            
            def install_missing():
                """Install missing dependencies."""
                status = self.get_dependency_status()
                missing = [pkg for pkg, info in status.items() if not info["installed"] and not info["optional"]]
                
                if not missing:
                    messagebox.showinfo("Info", "All required dependencies are already installed!")
                    return
                
                # Ask for confirmation
                missing_list = "\n".join([f"• {pkg}: {status[pkg]['description']}" for pkg in missing])
                result = messagebox.askyesno(
                    "Install Dependencies",
                    f"The following required dependencies are missing:\n\n{missing_list}\n\n"
                    f"Do you want to install them automatically?"
                )
                
                if result:
                    # Show progress bar
                    self.progress_bar.pack(fill="x", pady=(5, 0))
                    
                    def progress_callback(message, progress):
                        try:
                            self.status_label.configure(text=message)
                            self.progress_var.set(progress * 100)
                            checker_window.update()
                        except Exception as e:
                            print(f"Warning: Failed to update progress UI: {e}")
                    
                    # Install in background thread
                    def install_thread():
                        try:
                            success = self.install_dependencies(missing, progress_callback)
                            
                            # Schedule completion callback in main thread
                            checker_window.after(0, lambda: self._on_install_complete(success, missing, check_dependencies))
                        except Exception as e:
                            print(f"Error in install thread: {e}")
                            checker_window.after(0, lambda: self._on_install_complete(False, missing, None))
                    
                    import threading
                    thread = threading.Thread(target=install_thread, daemon=True)
                    thread.start()
            
            # Buttons
            ttk.Button(button_frame, text="Check Dependencies", 
                      command=check_dependencies,
                      style="App.Secondary.TButton").pack(side="left", padx=(0, 10))
            
            if missing_packages:
                ttk.Button(button_frame, text="Install Missing", 
                          command=install_missing,
                          style="App.Primary.TButton").pack(side="left", padx=(0, 10))
            
            ttk.Button(button_frame, text="Close", 
                      command=checker_window.destroy,
                      style="App.Secondary.TButton").pack(side="right")
            
            # Apply styles
            self._apply_window_styles(checker_window)
            
            # Center window
            checker_window.update_idletasks()
            x = (checker_window.winfo_screenwidth() // 2) - (checker_window.winfo_width() // 2)
            y = (checker_window.winfo_screenheight() // 2) - (checker_window.winfo_height() // 2)
            checker_window.geometry(f"+{x}+{y}")
            
            return checker_window
        except Exception as e:
            print(f"Error showing dependency checker: {e}")
            messagebox.showerror("Error", f"Failed to open Dependency Checker: {e}")
            return None
    
    def _on_install_complete(self, success: bool, packages: List[str], refresh_callback):
        """Handle installation completion."""
        try:
            self.progress_bar.pack_forget()
            self.progress_var.set(0)
            
            if success:
                messagebox.showinfo("Success", f"Successfully installed: {', '.join(packages)}")
                # Safely refresh the dependency status
                try:
                    refresh_callback()
                except Exception as e:
                    print(f"Warning: Failed to refresh dependency status: {e}")
            else:
                messagebox.showerror("Error", f"Failed to install some dependencies. Check console for details.")
        except Exception as e:
            print(f"Error in _on_install_complete: {e}")
            messagebox.showerror("Error", f"An error occurred during installation completion: {e}")
    
    def _apply_window_styles(self, window):
        """Apply PGLOK styles to the window."""
        try:
            style = ttk.Style()
            
            # Configure styles
            style.configure("App.TFrame", background=self.colors["bg"])
            style.configure("App.Card.TFrame", background=self.colors["card_bg"])
            style.configure("App.Panel.TFrame", background=self.colors["panel_bg"])
            style.configure("App.TLabel", background=self.colors["panel_bg"], 
                           foreground=self.colors["fg"])
            style.configure("App.Title.TLabel", background=self.colors["panel_bg"], 
                           foreground=self.colors["fg"], font=("Arial", 12, "bold"))
            style.configure("App.Status.TLabel", background=self.colors["panel_bg"], 
                           foreground=self.colors["primary"])
            style.configure("App.Primary.TButton", background=self.colors["primary"], 
                           foreground=self.colors["fg"])
            style.configure("App.Secondary.TButton", background=self.colors["secondary"], 
                           foreground=self.colors["fg"])
        except:
            pass  # Styles may already be configured
