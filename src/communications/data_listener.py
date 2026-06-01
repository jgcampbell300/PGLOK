"""
Data Listener for PGLOK Communications
Handles receiving and processing game data from MQTT topics.
"""

from typing import Dict, Any, Callable, Optional
import time

import src.config.mqtt_config as mqtt_config
from .mqtt_client import MqttClient


class DataListener:
    """Handles receiving game data from MQTT topics."""
    
    def __init__(self, mqtt_client: MqttClient):
        """
        Initialize data listener.
        
        Args:
            mqtt_client: Connected MQTT client instance
        """
        self.client = mqtt_client
        self.online_users: Dict[str, Dict[str, Any]] = {}
        self.chat_messages: list = []
        self.price_updates: list = []
        self.favor_updates: list = []
        
        # Channel messages storage
        self.channel_messages: Dict[str, list] = {}
        for channel in mqtt_config.DEFAULT_CHANNELS:
            self.channel_messages[channel] = []
        
        # Register callbacks
        self.client.subscribe(mqtt_config.MQTT_TOPIC_CHAT, self._on_chat_message)
        self.client.subscribe(mqtt_config.MQTT_TOPIC_PRICES, self._on_price_update)
        self.client.subscribe(mqtt_config.MQTT_TOPIC_FAVOR, self._on_favor_update)
        self.client.subscribe(mqtt_config.MQTT_TOPIC_PRESENCE, self._on_presence)
        self.client.subscribe(f"{mqtt_config.MQTT_TOPIC_CHANNELS}/#", self._on_channel_message)
        
        # Custom callbacks
        self.chat_callback: Optional[Callable] = None
        self.price_callback: Optional[Callable] = None
        self.favor_callback: Optional[Callable] = None
        self.presence_callback: Optional[Callable] = None
        self.channel_callback: Optional[Callable] = None
    
    def _on_chat_message(self, topic: str, data: Dict[str, Any]) -> None:
        """Handle incoming chat message."""
        if data.get("type") == "chat":
            self.chat_messages.append(data)
            # Keep only last 100 messages
            if len(self.chat_messages) > 100:
                self.chat_messages.pop(0)
            
            if self.chat_callback:
                self.chat_callback(data)
    
    def _on_price_update(self, topic: str, data: Dict[str, Any]) -> None:
        """Handle incoming price update."""
        if data.get("type") == "price":
            self.price_updates.append(data)
            # Keep only last 50 updates
            if len(self.price_updates) > 50:
                self.price_updates.pop(0)
            
            if self.price_callback:
                self.price_callback(data)
    
    def _on_favor_update(self, topic: str, data: Dict[str, Any]) -> None:
        """Handle incoming favor gain data."""
        if data.get("type") == "favor":
            self.favor_updates.append(data)
            # Keep only last 50 updates
            if len(self.favor_updates) > 50:
                self.favor_updates.pop(0)
            
            if self.favor_callback:
                self.favor_callback(data)
    
    def _on_presence(self, topic: str, data: Dict[str, Any]) -> None:
        """Handle incoming presence update."""
        if data.get("type") == "presence":
            user = data.get("user", "")
            if user:
                self.online_users[user] = data
                self._cleanup_offline_users()
                
                if self.presence_callback:
                    self.presence_callback(data)
    
    def _cleanup_offline_users(self) -> None:
        """Remove users who haven't been seen recently."""
        current_time = time.time()
        offline_users = []
        
        for user, data in self.online_users.items():
            last_seen = data.get("timestamp", 0)
            if current_time - last_seen > mqtt_config.MQTT_PRESENCE_TIMEOUT:
                offline_users.append(user)
        
        for user in offline_users:
            del self.online_users[user]
    
    def get_online_users(self) -> Dict[str, Dict[str, Any]]:
        """
        Get currently online users.
        
        Returns:
            Dictionary of user -> presence data
        """
        self._cleanup_offline_users()
        return self.online_users.copy()
    
    def get_chat_messages(self, limit: int = 50) -> list:
        """
        Get recent chat messages.
        
        Args:
            limit: Maximum number of messages to return
            
        Returns:
            List of chat message dictionaries
        """
        return self.chat_messages[-limit:]
    
    def get_price_updates(self, limit: int = 20) -> list:
        """
        Get recent price updates.
        
        Args:
            limit: Maximum number of updates to return
            
        Returns:
            List of price update dictionaries
        """
        return self.price_updates[-limit:]
    
    def get_favor_updates(self, limit: int = 20) -> list:
        """
        Get recent favor gain updates.
        
        Args:
            limit: Maximum number of updates to return
            
        Returns:
            List of favor update dictionaries
        """
        return self.favor_updates[-limit:]
    
    def set_chat_callback(self, callback: Callable) -> None:
        """Set callback function for chat messages."""
        self.chat_callback = callback
    
    def set_price_callback(self, callback: Callable) -> None:
        """Set callback function for price updates."""
        self.price_callback = callback
    
    def set_favor_callback(self, callback: Callable) -> None:
        """Set callback function for favor updates."""
        self.favor_callback = callback
    
    def set_presence_callback(self, callback: Callable) -> None:
        """Set callback function for presence updates."""
        self.presence_callback = callback
    
    def _on_channel_message(self, topic: str, data: Dict[str, Any]) -> None:
        """Handle incoming channel message."""
        channel = data.get("channel", "")
        if not channel:
            return
        
        # Initialize channel list if not exists
        if channel not in self.channel_messages:
            self.channel_messages[channel] = []
        
        self.channel_messages[channel].append(data)
        # Keep only last 100 messages per channel
        if len(self.channel_messages[channel]) > 100:
            self.channel_messages[channel].pop(0)
        
        if self.channel_callback:
            self.channel_callback(channel, data)
    
    def get_channel_messages(self, channel: str, limit: int = 50) -> list:
        """
        Get recent messages from a specific channel.
        
        Args:
            channel: Channel name
            limit: Maximum number of messages to return
            
        Returns:
            List of channel message dictionaries
        """
        if channel not in self.channel_messages:
            return []
        return self.channel_messages[channel][-limit:]
    
    def get_active_channels(self) -> list:
        """
        Get list of channels with messages.
        
        Returns:
            List of channel names
        """
        return list(self.channel_messages.keys())
    
    def add_channel(self, channel: str) -> None:
        """
        Add a new channel to track.
        
        Args:
            channel: Channel name
        """
        if channel not in self.channel_messages:
            self.channel_messages[channel] = []
    
    def set_channel_callback(self, callback: Callable) -> None:
        """Set callback function for channel messages."""
        self.channel_callback = callback
