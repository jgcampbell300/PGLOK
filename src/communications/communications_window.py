"""
Communications Window for PGLOK
Provides chat and data sharing interface via MQTT with support for multiple channels.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, simpledialog, messagebox
import threading
import time
import re
import json
from datetime import datetime

import src.config.mqtt_config as mqtt_config
from src.config import config
from src.config.ui_theme import apply_theme, UI_COLORS
from src.config.window_state import setup_window
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
        
        # Create window with state persistence
        self.window = tk.Toplevel(parent)
        setup_window(
            self.window,
            "communications",
            min_w=800,
            min_h=600,
            default_geometry="900x650",
            on_close=self._on_close
        )
        self.window.title(f"PGLOK Communications - {character_name}")
        
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
        
        # Channel management
        self.channels = list(mqtt_config.DEFAULT_CHANNELS)
        self.channel_notebook = None
        self.channel_tabs = {}  # channel_name -> {text_widget, input_widget}
        self.current_channel = self.channels[0] if self.channels else "general"
        
        # Always on top state
        self.always_on_top_var = tk.BooleanVar(value=False)
        if hasattr(self.parent, "_get_ui_pref"):
            try:
                saved_pin = bool(self.parent._get_ui_pref("communications_always_on_top", False))
            except Exception:
                saved_pin = False
            self.always_on_top_var.set(saved_pin)
            if saved_pin:
                try:
                    self.window.attributes("-topmost", True)
                except Exception:
                    pass
        
        self._setup_ui()
        self._connect_mqtt()
    
    def _setup_ui(self):
        """Setup the UI components."""
        # Main container
        main_paned = ttk.PanedWindow(self.window, orient=tk.HORIZONTAL, style="App.TPanedwindow")
        main_paned.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)
        
        # Left side: Channels
        channels_frame = ttk.Frame(main_paned, style="App.Panel.TFrame", padding=12)
        main_paned.add(channels_frame, weight=3)
        
        # Header with title and status
        header_frame = ttk.Frame(channels_frame, style="App.Panel.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 12))
        
        ttk.Label(header_frame, text="PGLOK Communications", font=("Segoe UI", 14, "bold"), 
                 foreground=UI_COLORS["text"], background=UI_COLORS["panel_bg"]).pack(side=tk.LEFT)
        
        # Always on top toggle
        ttk.Checkbutton(
            header_frame,
            text="Always on Top",
            variable=self.always_on_top_var,
            command=self._toggle_always_on_top,
            style="App.TCheckbutton",
        ).pack(side=tk.RIGHT, padx=(0, 10))
        
        ttk.Label(header_frame, textvariable=self.status_var, 
                 foreground=UI_COLORS["muted_text"], background=UI_COLORS["panel_bg"]).pack(side=tk.RIGHT)
        
        # Channel management buttons
        channel_buttons_frame = ttk.Frame(channels_frame, style="App.Panel.TFrame")
        channel_buttons_frame.pack(fill=tk.X, pady=(0, 8))
        
        ttk.Button(channel_buttons_frame, text="+ New Channel", command=self._create_new_channel, 
                  style="App.Secondary.TButton").pack(side=tk.LEFT)
        
        ttk.Label(channel_buttons_frame, text="This chat is separate from in-game chat.", 
                 foreground=UI_COLORS["muted_text"], background=UI_COLORS["panel_bg"]).pack(side=tk.RIGHT)
        
        # Channel tabs notebook
        self.channel_notebook = ttk.Notebook(channels_frame, style="App.TNotebook")
        self.channel_notebook.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        
        # Create default channel tabs
        for channel in self.channels:
            self._create_channel_tab(channel)
        
        # Bind tab change event
        self.channel_notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        
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
    
    def _create_channel_tab(self, channel_name: str):
        """Create a tab for a channel."""
        tab_frame = ttk.Frame(self.channel_notebook, style="App.Panel.TFrame", padding=8)
        self.channel_notebook.add(tab_frame, text=channel_name)
        
        # Channel description
        if channel_name == "pglok-data":
            desc = "Data channel for PGLOK instances to share information."
        else:
            desc = f"Channel: {channel_name}"
        
        desc_label = ttk.Label(tab_frame, text=desc, foreground=UI_COLORS["muted_text"],
                              background=UI_COLORS["panel_bg"], font=("Segoe UI", 9))
        desc_label.pack(fill=tk.X, pady=(0, 8))
        
        # Chat messages
        chat_text = scrolledtext.ScrolledText(
            tab_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            height=18,
            bg=UI_COLORS["card_bg"],
            fg="#e6eef6",
            font=("Segoe UI", 10),
            insertbackground="#e6eef6",
            selectbackground=UI_COLORS["primary"],
            relief="flat",
            borderwidth=0
        )
        chat_text.pack(fill=tk.BOTH, expand=True)
        
        # Chat input
        input_frame = ttk.Frame(tab_frame, style="App.Panel.TFrame")
        input_frame.pack(fill=tk.X, pady=(8, 0))
        
        chat_input = ttk.Entry(input_frame, style="App.TEntry")
        chat_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        chat_input.bind("<Return>", lambda event: self._send_channel_message(channel_name))
        
        send_button = ttk.Button(input_frame, text="Send", 
                               command=lambda: self._send_channel_message(channel_name),
                               style="App.Primary.TButton")
        send_button.pack(side=tk.RIGHT, padx=(8, 0))
        
        # Store widgets
        self.channel_tabs[channel_name] = {
            "text_widget": chat_text,
            "input_widget": chat_input
        }
    
    def _create_new_channel(self):
        """Prompt user to create a new channel."""
        channel_name = simpledialog.askstring(
            "New Channel",
            "Enter channel name:",
            parent=self.window
        )
        
        if channel_name and channel_name.strip():
            channel_name = channel_name.strip().lower()
            # Remove invalid characters
            channel_name = re.sub(r'[^a-z0-9\-]', '', channel_name)
            
            if not channel_name:
                messagebox.showerror("Error", "Invalid channel name")
                return
            
            if channel_name in self.channels:
                messagebox.showerror("Error", "Channel already exists")
                return
            
            self.channels.append(channel_name)
            self._create_channel_tab(channel_name)
            
            # Add to listener
            if self.listener:
                self.listener.add_channel(channel_name)
            
            # Switch to new channel
            for i, tab_id in enumerate(self.channel_notebook.tabs()):
                if self.channel_notebook.tab(tab_id, "text") == channel_name:
                    self.channel_notebook.select(tab_id)
                    break
    
    def _on_tab_changed(self, event):
        """Handle tab change event."""
        selected_tab = self.channel_notebook.select()
        if selected_tab:
            tab_text = self.channel_notebook.tab(selected_tab, "text")
            self.current_channel = tab_text
    
    def _toggle_always_on_top(self):
        """Toggle always on top state."""
        try:
            if self.always_on_top_var.get():
                self.window.attributes("-topmost", True)
            else:
                self.window.attributes("-topmost", False)
            
            # Save preference
            if hasattr(self.parent, "_set_ui_pref"):
                try:
                    self.parent._set_ui_pref("communications_always_on_top", bool(self.always_on_top_var.get()))
                except Exception:
                    pass
        except Exception:
            pass
    
    def _send_channel_message(self, channel: str):
        """Send message to a specific channel."""
        if channel not in self.channel_tabs:
            return
        
        input_widget = self.channel_tabs[channel]["input_widget"]
        message = input_widget.get().strip()
        
        if message and self.publisher:
            if self.publisher.publish_channel_message(channel, message):
                input_widget.delete(0, tk.END)
            else:
                self._add_channel_message(channel, "System", "Rate limited - please wait", "gray")
    
    def _add_channel_message(self, channel: str, user: str, message: str, color: str = None):
        """Add message to a specific channel."""
        if channel not in self.channel_tabs:
            return
        
        text_widget = self.channel_tabs[channel]["text_widget"]
        timestamp = datetime.now().strftime("%H:%M:%S")
        text_widget.config(state=tk.NORMAL)
        
        # Use light colors for visibility on dark background
        if color is None:
            color = "#e6eef6"
        elif color == "black":
            color = "#e6eef6"
        elif color == "gray":
            color = "#9fb4c9"
        
        text_widget.insert(tk.END, f"[{timestamp}] {user}: {message}\n")
        text_widget.see(tk.END)
        text_widget.config(state=tk.DISABLED)
    
    def _connect_mqtt(self):
        """Connect to MQTT broker asynchronously."""
        if not mqtt_config.MQTT_ENABLED:
            self.status_var.set("Communications disabled")
            return
        
        self.status_var.set("Connecting...")
        
        # Start connection in background thread to avoid blocking UI
        connection_thread = threading.Thread(target=self._connect_mqtt_async, daemon=True)
        connection_thread.start()
    
    def _connect_mqtt_async(self):
        """Async MQTT connection worker."""
        try:
            self.mqtt_client = MqttClient(self.character_name)
            connected_ok = self.mqtt_client.connect()

            if not connected_ok:
                self._update_status_safe("Connection failed")
                return

            # Wait a short while for the on_connect callback to set connected=True
            # But don't block the UI - just check periodically
            waited = 0.0
            wait_step = 0.1
            max_wait = 8.0
            while waited < max_wait and not getattr(self.mqtt_client, 'connected', False):
                time.sleep(wait_step)
                waited += wait_step

            if not getattr(self.mqtt_client, 'connected', False):
                # Still not connected
                self._update_status_safe("Connection failed")
                # Cleanup client
                try:
                    self.mqtt_client.disconnect()
                except Exception:
                    pass
                return

            # Now that the underlying client reports connected, create publisher/listener
            self.publisher = DataPublisher(self.mqtt_client)
            self.listener = DataListener(self.mqtt_client)

            # Set callbacks
            self.listener.set_chat_callback(self._on_chat_message)
            self.listener.set_presence_callback(self._on_presence_update)
            self.listener.set_channel_callback(self._on_channel_message)
            # Favor updates
            try:
                self.listener.set_favor_callback(self._on_favor_message)
            except Exception:
                pass

            self._update_status_safe("Connected")

            # Flush any pending publishes queued while disconnected
            try:
                self._flush_pending_publishes()
            except Exception:
                pass

            # Start heartbeat
            self._start_heartbeat()
        except Exception as e:
            self._update_status_safe(f"Error: {e}")
    
    def _update_status_safe(self, status: str):
        """Thread-safe status update."""
        try:
            if self.window and self.window.winfo_exists():
                self.window.after(0, lambda: self.status_var.set(status))
        except Exception:
            pass
    
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

    def _on_favor_message(self, data: dict) -> None:
        """Handle incoming favor update messages (from other users)."""
        try:
            user = data.get("user", "Unknown")
            npc = data.get("npc", "")
            item = data.get("item", "")
            favor = data.get("favor")
            msg = f"[FAVOR] {npc}: +{favor} from {item} (shared by {user})"
            self._add_chat_message("Comm", msg)

            # If the main app/favor tracker is open, persist this externally-shared record
            try:
                app = getattr(self.parent, "app", None)
                if app and hasattr(app, "favor_tracker_window") and app.favor_tracker_window:
                    try:
                        app.favor_tracker_window.record_external_favor(npc, item, favor, user)
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass
    
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
    
    def _on_channel_message(self, channel: str, data: dict):
        """Handle incoming channel message."""
        # Check if window still exists
        try:
            if not self.window.winfo_exists():
                return
        except Exception:
            return
        
        user = data.get("user", "Unknown")
        msg_type = data.get("type", "chat")
        
        if msg_type == "chat":
            message = data.get("message", "")
            self._add_channel_message(channel, user, message)
        elif msg_type == "data":
            # Handle data messages (for pglok-data channel)
            data_dict = data.get("data", {})
            self._add_channel_message(channel, user, f"[DATA] {data_dict}", "gray")
    
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
        """Handle window close - cleanup MQTT and destroy window."""
        if hasattr(self.parent, 'app'):
            self.parent.app._set_window_open_state("communications", False)
        self._cleanup_mqtt()
        # Window state is automatically saved by setup_window
    
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
    
    def _flush_pending_publishes(self):
        """Attempt to publish any queued publishes saved while disconnected."""
        try:
            pending_path = config.DATA_DIR / "pending_publishes.json"
            if not pending_path.exists():
                return
            try:
                with pending_path.open("r", encoding="utf-8") as pf:
                    pending = json.load(pf)
            except Exception:
                pending = []
            if not pending:
                try:
                    pending_path.unlink()
                except Exception:
                    pass
                return

            remaining = []
            for entry in pending:
                favor_data = entry.get("favor_data") or entry.get("data") or entry
                try:
                    if self.publisher and self.publisher.publish_data_to_channel("pglok-data", "favor", favor_data):
                        # Inform the channel UI that we flushed a queued publish
                        try:
                            self._add_channel_message("pglok-data", "System", f"Flushed pending favor publish for {favor_data.get('npc', favor_data.get('npc_key','?'))}", "gray")
                        except Exception:
                            pass
                    else:
                        remaining.append(entry)
                except Exception:
                    remaining.append(entry)

            try:
                if remaining:
                    with pending_path.open("w", encoding="utf-8") as pf:
                        json.dump(remaining, pf, indent=2, ensure_ascii=False)
                else:
                    try:
                        pending_path.unlink()
                    except Exception:
                        pass
            except Exception as e:
                print(f"Error updating pending publishes file: {e}")
        except Exception as e:
            print(f"Failed to flush pending publishes: {e}")

    def close(self):
        """Close the communications window."""
        self._cleanup_mqtt()
        self.window.destroy()
    
    def publish_instance_data(self, data_type: str, data_dict: dict) -> bool:
        """
        Publish PGLOK instance data to the pglok-data channel.
        This method can be called from the main app to share information between instances.
        
        Args:
            data_type: Type of data (e.g., "position", "inventory", "status", "character")
            data_dict: Dictionary of data to publish
            
        Returns:
            True if publish successful, False otherwise
        """
        if self.publisher:
            return self.publisher.publish_data_to_channel("pglok-data", data_type, data_dict)
        return False
    
    def publish_chat_to_channel(self, channel: str, message: str) -> bool:
        """
        Publish a chat message to a specific channel.
        
        Args:
            channel: Channel name
            message: Message to send
            
        Returns:
            True if publish successful, False otherwise
        """
        if self.publisher:
            return self.publisher.publish_channel_message(channel, message)
        return False
