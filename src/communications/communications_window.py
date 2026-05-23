"""
Communications Window for PGLOK
Provides chat and data sharing interface via MQTT.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import time
from datetime import datetime

import src.config.mqtt_config as mqtt_config
from src.config.ui_theme import apply_theme, UI_COLORS
from .mqtt_client import MqttClient
from .data_publisher import DataPublisher
from .data_listener import DataListener


class CommunicationsWindow:
    """Window for PGLOK communications (chat, data sharing, online users)."""
    
    def __init__(self, parent, character_name: str = "Unknown"):
        """
        Initialize communications window.
        
        Args:
            parent: Parent Tkinter window
            character_name: Player's character name
        """
        self.parent = parent
        self.character_name = character_name
        self.window = tk.Toplevel(parent)
        self.window.title(f"PGLOK Communications - {character_name}")
        self.window.geometry("800x600")
        
        # Apply PGLOK theme
        apply_theme(self.window)
        
        # Bind close event to save state
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # MQTT components
        self.mqtt_client = None
        self.publisher = None
        self.listener = None
        self.heartbeat_thread = None
        self.heartbeat_running = False
        
        # UI components
        self.chat_text = None
        self.chat_input = None
        self.online_users_tree = None
        self.status_var = tk.StringVar(value="Disconnected")
        
        self._setup_ui()
        self._connect_mqtt()
    
    def _setup_ui(self):
        """Setup the UI components."""
        # Main container
        main_paned = ttk.PanedWindow(self.window, orient=tk.HORIZONTAL, style="App.TPanedwindow")
        main_paned.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)
        
        # Left side: Chat
        chat_frame = ttk.Frame(main_paned, style="App.Panel.TFrame", padding=12)
        main_paned.add(chat_frame, weight=3)
        
        # Chat header
        header_frame = ttk.Frame(chat_frame, style="App.Panel.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 12))
        
        ttk.Label(header_frame, text="PGLOK Chat", font=("Segoe UI", 14, "bold"), 
                 foreground=UI_COLORS["text"], background=UI_COLORS["panel_bg"]).pack(side=tk.LEFT)
        ttk.Label(header_frame, textvariable=self.status_var, 
                 foreground=UI_COLORS["muted_text"], background=UI_COLORS["panel_bg"]).pack(side=tk.RIGHT)
        
        # Notice label
        notice_text = "This chat is separate from in-game chat and cannot send messages into the game."
        notice_label = tk.Label(chat_frame, text=notice_text, foreground=UI_COLORS["muted_text"],
                              background=UI_COLORS["panel_bg"], wraplength=500, justify=tk.LEFT)
        notice_label.pack(fill=tk.X, pady=(0, 12))
        
        # Chat messages
        self.chat_text = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            height=20,
            bg=UI_COLORS["card_bg"],
            fg="#e6eef6",  # Light text for visibility
            font=("Segoe UI", 10),
            insertbackground="#e6eef6",
            selectbackground=UI_COLORS["primary"],
            relief="flat",
            borderwidth=0
        )
        self.chat_text.pack(fill=tk.BOTH, expand=True)
        
        # Chat input
        input_frame = ttk.Frame(chat_frame, style="App.Panel.TFrame")
        input_frame.pack(fill=tk.X, pady=(12, 0))
        
        self.chat_input = ttk.Entry(input_frame, style="App.TEntry")
        self.chat_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.chat_input.bind("<Return>", self._send_chat_message)
        
        send_button = ttk.Button(input_frame, text="Send", command=self._send_chat_message, style="App.Primary.TButton")
        send_button.pack(side=tk.RIGHT, padx=(8, 0))
        
        # Right side: Online users
        users_frame = ttk.Frame(main_paned, style="App.Panel.TFrame", padding=12)
        main_paned.add(users_frame, weight=1)
        
        ttk.Label(users_frame, text="Online Users", font=("Segoe UI", 12, "bold"),
                 foreground=UI_COLORS["text"], background=UI_COLORS["panel_bg"]).pack(pady=(0, 12))
        
        # Online users treeview
        columns = ("Player", "Status", "Area")
        self.online_users_tree = ttk.Treeview(users_frame, columns=columns, show="headings", height=20,
                                              style="App.Treeview", selectmode="browse")
        self.online_users_tree.heading("Player", text="Player")
        self.online_users_tree.heading("Status", text="Status")
        self.online_users_tree.heading("Area", text="Area")
        
        self.online_users_tree.column("Player", width=100, anchor=tk.W)
        self.online_users_tree.column("Status", width=80, anchor=tk.CENTER)
        self.online_users_tree.column("Area", width=100, anchor=tk.W)
        
        # Scrollbar for treeview
        tree_vsb = ttk.Scrollbar(users_frame, orient="vertical", command=self.online_users_tree.yview)
        self.online_users_tree.configure(yscrollcommand=tree_vsb.set)
        
        self.online_users_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_vsb.pack(side=tk.RIGHT, fill=tk.Y)
    
    def _connect_mqtt(self):
        """Connect to MQTT broker."""
        if not mqtt_config.MQTT_ENABLED:
            self.status_var.set("Communications disabled")
            return
        
        try:
            self.mqtt_client = MqttClient(self.character_name)
            if self.mqtt_client.connect():
                self.publisher = DataPublisher(self.mqtt_client)
                self.listener = DataListener(self.mqtt_client)
                
                # Set callbacks
                self.listener.set_chat_callback(self._on_chat_message)
                self.listener.set_presence_callback(self._on_presence_update)
                
                self.status_var.set("Connected")
                
                # Start heartbeat
                self._start_heartbeat()
            else:
                self.status_var.set("Connection failed")
        except Exception as e:
            self.status_var.set(f"Error: {e}")
    
    def _start_heartbeat(self):
        """Start presence heartbeat thread."""
        self.heartbeat_running = True
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
    
    def _heartbeat_loop(self):
        """Send periodic presence updates."""
        while self.heartbeat_running and self.mqtt_client and self.mqtt_client.connected:
            if self.publisher:
                self.publisher.publish_presence(status="Online")
            time.sleep(mqtt_config.MQTT_PRESENCE_INTERVAL)
    
    def _send_chat_message(self, event=None):
        """Send chat message."""
        message = self.chat_input.get().strip()
        if message and self.publisher:
            if self.publisher.publish_chat_message(message):
                self.chat_input.delete(0, tk.END)
            else:
                self._add_chat_message("System", "Rate limited - please wait", "gray")
    
    def _on_chat_message(self, data: dict):
        """Handle incoming chat message."""
        # Check if window still exists
        try:
            if not self.window.winfo_exists():
                return
        except Exception:
            return
        
        user = data.get("user", "Unknown")
        message = data.get("message", "")
        self._add_chat_message(user, message)
    
    def _on_presence_update(self, data: dict):
        """Handle presence update."""
        self._refresh_online_users()
    
    def _add_chat_message(self, user: str, message: str, color: str = None):
        """Add message to chat display."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.chat_text.config(state=tk.NORMAL)
        
        # Use light colors for visibility on dark background
        if color is None:
            color = "#e6eef6"  # Light gray-white
        elif color == "black":
            color = "#e6eef6"
        elif color == "gray":
            color = "#9fb4c9"  # Muted light gray
        
        self.chat_text.insert(tk.END, f"[{timestamp}] {user}: {message}\n")
        self.chat_text.see(tk.END)
        self.chat_text.config(state=tk.DISABLED)
    
    def _refresh_online_users(self):
        """Refresh online users list."""
        if not self.listener:
            return
        
        # Check if window still exists
        try:
            if not self.window.winfo_exists():
                return
        except Exception:
            return
        
        # Check if treeview still exists
        try:
            if not self.online_users_tree.winfo_exists():
                return
        except Exception:
            return
        
        # Clear existing items
        for item in self.online_users_tree.get_children():
            self.online_users_tree.delete(item)
        
        # Add online users
        online_users = self.listener.get_online_users()
        for user, data in online_users.items():
            status = data.get("status", "Unknown")
            area = data.get("area", "")
            self.online_users_tree.insert("", tk.END, values=(user, status, area))
    
    def _on_close(self):
        """Handle window close - save state and cleanup."""
        self._save_window_geometry()
        if hasattr(self.parent, 'app'):
            self.parent.app._set_window_open_state("communications", False)
        self._cleanup_mqtt()
        self.window.destroy()
    
    def _cleanup_mqtt(self):
        """Clean up MQTT connections without blocking."""
        self.heartbeat_running = False
        if self.mqtt_client:
            try:
                if self.publisher:
                    self.publisher.publish_presence(status="Offline")
                # Don't wait for disconnect, just stop the loop
                self.mqtt_client.client.loop_stop(force=True)
            except Exception:
                pass
    
    def close(self):
        """Close the communications window."""
        self._cleanup_mqtt()
        self.window.destroy()
