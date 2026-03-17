"""
Simple dependency checker that won't crash PGLOK
"""

import subprocess
import sys
import importlib
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from src.config.ui_theme import UI_COLORS

class SimpleDependencyChecker:
    """Simple dependency checker with crash protection."""
    
    def __init__(self, parent_app):
        self.parent_app = parent_app
        
        # Define required dependencies
        self.dependencies = {
            "requests": {
                "version": ">=2.25.0",
                "description": "HTTP library for web requests",
                "optional": False
            },
            "psutil": {
                "version": ">=5.8.0", 
                "description": "System and process utilities",
                "optional": False
            },
            "pynput": {
                "version": ">=1.7.6",
                "description": "Keyboard and mouse input capture (for BamBam macros)",
                "optional": True
            }
        }
    
    def check_dependencies(self):
        """Check which dependencies are installed."""
        installed = []
        missing = []
        
        for package, info in self.dependencies.items():
            try:
                importlib.import_module(package)
                installed.append(package)
            except ImportError:
                missing.append(package)
        
        return installed, missing
    
    def get_status(self):
        """Get detailed status of all dependencies."""
        status = {}
        
        for package, info in self.dependencies.items():
            try:
                module = importlib.import_module(package)
                version = getattr(module, '__version__', 'Unknown')
                
                status[package] = {
                    "installed": True,
                    "version": version,
                    "description": info["description"],
                    "optional": info["optional"]
                }
            except ImportError:
                status[package] = {
                    "installed": False,
                    "version": None,
                    "description": info["description"],
                    "optional": info["optional"]
                }
        
        return status
    
    def show_checker(self):
        """Show simple dependency checker window."""
        try:
            # Check if parent app and root exist
            if not self.parent_app or not hasattr(self.parent_app, 'root') or not self.parent_app.root:
                messagebox.showerror("Error", "PGLOK application window not available")
                return False
            
            # Create simple window
            window = tk.Toplevel(self.parent_app.root)
            window.title("PGLOK Dependencies")
            window.geometry("600x400")
            window.transient(self.parent_app.root)
            
            # Main frame
            main_frame = tk.Frame(window, bg=UI_COLORS["bg"], padx=20, pady=20)
            main_frame.pack(fill="both", expand=True)
            
            # Title
            title = tk.Label(main_frame, text="Dependency Status", 
                           bg=UI_COLORS["bg"], fg=UI_COLORS["text"], font=("Arial", 14, "bold"))
            title.pack(pady=(0, 20))
            
            # Status text
            status_text = tk.Text(main_frame, bg=UI_COLORS["entry_bg"], fg=UI_COLORS["text"], 
                                font=("Courier", 10), height=15, width=70)
            status_text.pack(fill="both", expand=True, pady=(0, 10))
            
            # Add scrollbar
            scrollbar = tk.Scrollbar(main_frame, command=status_text.yview)
            scrollbar.pack(side="right", fill="y")
            status_text.configure(yscrollcommand=scrollbar.set)
            
            # Get and display status
            status = self.get_status()
            
            # Check which dependencies are missing
            installed, missing = self.check_dependencies()
            
            status_text.insert("1.0", "PGLOK Dependency Status\n")
            status_text.insert("end", "=" * 50 + "\n\n")
            
            for package, info in status.items():
                status_symbol = "✓" if info["installed"] else "✗"
                version = info["version"] if info["version"] else "Not installed"
                optional = "(Optional)" if info["optional"] else "(Required)"
                
                status_text.insert("end", f"{status_symbol} {package}\n")
                status_text.insert("end", f"  Version: {version}\n")
                status_text.insert("end", f"  Status: {optional}\n")
                status_text.insert("end", f"  Description: {info['description']}\n\n")
            
            # Close button
            button_frame = tk.Frame(main_frame, bg=UI_COLORS["bg"])
            button_frame.pack(fill="x", pady=(10, 0))
            
            # Install button for missing dependencies
            if missing:
                install_btn = tk.Button(button_frame, text="Install Missing Dependencies", 
                                     command=lambda: self._install_missing(window),
                                     bg=UI_COLORS["primary"], fg=UI_COLORS["text"], font=("Arial", 10))
                install_btn.pack(side="left", padx=(0, 10))
            
            close_btn = tk.Button(button_frame, text="Close", command=lambda: self._close_window(window),
                           bg=UI_COLORS["primary"], fg=UI_COLORS["text"], font=("Arial", 10))
            close_btn.pack(side="right")
            
            # Center window
            window.update_idletasks()
            x = (window.winfo_screenwidth() // 2) - (window.winfo_width() // 2)
            y = (window.winfo_screenheight() // 2) - (window.winfo_height() // 2)
            window.geometry(f"+{x}+{y}")
            
            return True
            
        except Exception as e:
            print(f"Error in simple dependency checker: {e}")
            messagebox.showerror("Error", f"Failed to show dependency checker: {e}")
            return False
    
    def _close_window(self, window):
        """Close window with a small delay to let user see the status."""
        try:
            # Add a small delay before closing
            window.after(500, window.destroy)
        except:
            try:
                window.destroy()
            except:
                pass
    
    def _install_missing(self, parent_window):
        """Install missing dependencies."""
        try:
            installed, missing = self.check_dependencies()
            
            if not missing:
                messagebox.showinfo("Info", "All dependencies are already installed!")
                return
            
            # Create list of missing packages with info
            missing_info = []
            for pkg in missing:
                if pkg in self.dependencies:
                    info = self.dependencies[pkg]
                    missing_info.append(f"• {pkg}: {info['description']}")
            
            # Ask for confirmation
            missing_list = "\n".join(missing_info)
            result = messagebox.askyesno(
                "Install Dependencies",
                f"The following dependencies are missing:\n\n{missing_list}\n\n"
                f"Do you want to install them?"
            )
            
            if result:
                self._perform_installation(missing, parent_window)
        
        except Exception as e:
            print(f"Error in install missing: {e}")
            messagebox.showerror("Error", f"Failed to install dependencies: {e}")
    
    def _perform_installation(self, packages, parent_window):
        """Perform the actual installation."""
        try:
            # Create progress window
            progress_window = tk.Toplevel(parent_window)
            progress_window.title("Installing Dependencies")
            progress_window.geometry("400x150")
            progress_window.transient(parent_window)
            progress_window.grab_set()
            
            # Progress frame
            frame = tk.Frame(progress_window, bg=UI_COLORS["bg"], padx=20, pady=20)
            frame.pack(fill="both", expand=True)
            
            # Status label
            status_label = tk.Label(frame, text="Installing dependencies...", 
                                  bg=UI_COLORS["bg"], fg=UI_COLORS["text"], font=("Arial", 10))
            status_label.pack(pady=(0, 10))
            
            # Progress bar
            progress_var = tk.DoubleVar()
            progress_bar = ttk.Progressbar(frame, variable=progress_var, 
                                          mode="determinate", length=300)
            progress_bar.pack(pady=(0, 10))
            
            # Package label
            package_label = tk.Label(frame, text="", bg=UI_COLORS["bg"], fg=UI_COLORS["text"], 
                                    font=("Arial", 9))
            package_label.pack()
            
            def update_progress(package, progress, message):
                """Update progress UI."""
                try:
                    status_label.configure(text=message)
                    package_label.configure(text=f"Installing: {package}")
                    progress_var.set(progress)
                    progress_window.update()
                except:
                    pass
            
            def install_in_background():
                """Installation in background thread."""
                try:
                    success = True
                    total_packages = len(packages)
                    
                    for i, package in enumerate(packages):
                        update_progress(package, 0, f"Installing {package}...")
                        
                        # Get version requirement
                        version_spec = ">=0.0.0"
                        if package in self.dependencies:
                            version_spec = self.dependencies[package]["version"]
                        
                        install_spec = f"{package}{version_spec}"
                        
                        try:
                            # Install the package with system override for externally managed environments
                            result = subprocess.run(
                                [sys.executable, "-m", "pip", "install", install_spec, "--break-system-packages"],
                                capture_output=True,
                                text=True,
                                timeout=300  # 5 minute timeout
                            )
                            
                            if result.returncode == 0:
                                update_progress(package, (i + 1) / total_packages, 
                                             f"Successfully installed {package}")
                            else:
                                update_progress(package, (i + 1) / total_packages, 
                                             f"Failed to install {package}")
                                success = False
                                print(f"Failed to install {package}: {result.stderr}")
                        
                        except subprocess.TimeoutExpired:
                            update_progress(package, (i + 1) / total_packages, 
                                         f"Timeout installing {package}")
                            success = False
                            print(f"Timeout installing {package}")
                        
                        except Exception as e:
                            update_progress(package, (i + 1) / total_packages, 
                                         f"Error installing {package}")
                            success = False
                            print(f"Error installing {package}: {e}")
                    
                    # Show completion message in main thread
                    progress_window.after(0, lambda: self._installation_complete(success, packages, progress_window))
                
                except Exception as e:
                    print(f"Error in installation thread: {e}")
                    progress_window.after(0, lambda: self._installation_complete(False, packages, progress_window))
            
            # Start installation in background thread
            import threading
            thread = threading.Thread(target=install_in_background, daemon=True)
            thread.start()
            
            # Center progress window
            progress_window.update_idletasks()
            x = (progress_window.winfo_screenwidth() // 2) - (progress_window.winfo_width() // 2)
            y = (progress_window.winfo_screenheight() // 2) - (progress_window.winfo_height() // 2)
            progress_window.geometry(f"+{x}+{y}")
        
        except Exception as e:
            print(f"Error in perform installation: {e}")
            messagebox.showerror("Error", f"Failed to start installation: {e}")
    
    def _installation_complete(self, success, packages, progress_window):
        """Handle installation completion."""
        try:
            progress_window.destroy()
            
            if success:
                messagebox.showinfo("Success", f"Successfully installed: {', '.join(packages)}")
                # Wait a bit before refreshing to let user see the message
                self.parent_app.root.after(2000, self.show_checker)
            else:
                messagebox.showerror("Error", f"Failed to install some dependencies. Check console for details.")
        
        except Exception as e:
            print(f"Error in installation complete: {e}")

def safe_show_dependency_checker(pglok_app):
    """Safely show dependency checker without crashing."""
    try:
        checker = SimpleDependencyChecker(pglok_app)
        return checker.show_checker()
    except Exception as e:
        print(f"Error in safe dependency checker: {e}")
        messagebox.showerror("Error", f"Failed to open dependency checker: {e}")
        return False
