"""
Data Publisher for PGLOK Communications
Provides functions to publish different types of game data via MQTT.
"""

from typing import TYPE_CHECKING

import src.config.mqtt_config as mqtt_config

if TYPE_CHECKING:
    from .mqtt_client import MqttClient


class DataPublisher:
    """Handles publishing game data to MQTT topics."""
    
    def __init__(self, mqtt_client: MqttClient):
        """
        Initialize data publisher.
        
        Args:
            mqtt_client: Connected MQTT client instance
        """
        self.client = mqtt_client
    
    def publish_price(self, item_name: str, price: int) -> bool:
        """
        Publish item price update.
        
        Args:
            item_name: Name of the item
            price: Price of the item
            
        Returns:
            True if publish successful
        """
        if not mqtt_config.MQTT_DATA_SHARING_ENABLED:
            return False
            
        data = {
            "type": "price",
            "item": item_name,
            "price": price
        }
        return self.client.publish(mqtt_config.MQTT_TOPIC_PRICES, data, rate_limit_key="prices")
    
    def publish_favor_gain(self, npc_name: str, item_name: str, favor: float) -> bool:
        """
        Publish favor gain data.
        
        Args:
            npc_name: Name of the NPC
            item_name: Name of the gifted item
            favor: Favor amount gained
            
        Returns:
            True if publish successful
        """
        if not mqtt_config.MQTT_DATA_SHARING_ENABLED:
            return False
            
        data = {
            "type": "favor",
            "npc": npc_name,
            "item": item_name,
            "favor": favor
        }
        return self.client.publish(mqtt_config.MQTT_TOPIC_FAVOR, data, rate_limit_key="favor")
    
    def publish_chat_message(self, message: str) -> bool:
        """
        Publish chat message.
        
        Args:
            message: Chat message text
            
        Returns:
            True if publish successful
        """
        if not mqtt_config.MQTT_CHAT_ENABLED:
            return False
            
        # Truncate if too long
        if len(message) > mqtt_config.MQTT_MAX_CHAT_LENGTH:
            message = message[:mqtt_config.MQTT_MAX_CHAT_LENGTH]
            
        data = {
            "type": "chat",
            "message": message
        }
        return self.client.publish(mqtt_config.MQTT_TOPIC_CHAT, data, rate_limit_key="chat")
    
    def publish_presence(self, status: str = "Online", area: str = "") -> bool:
        """
        Publish presence/online status.
        
        Args:
            status: User status (e.g., "Online", "Offline")
            area: Current area/zone
            
        Returns:
            True if publish successful
        """
        data = {
            "type": "presence",
            "status": status,
            "area": area
        }
        return self.client.publish(mqtt_config.MQTT_TOPIC_PRESENCE, data, rate_limit_key="presence")
    
    def publish_channel_message(self, channel: str, message: str, msg_type: str = "chat") -> bool:
        """
        Publish message to a specific channel.
        
        Args:
            channel: Channel name (e.g., "general", "pglok-data")
            message: Message content
            msg_type: Type of message (chat, data, etc.)
            
        Returns:
            True if publish successful
        """
        if not mqtt_config.MQTT_CHAT_ENABLED and msg_type == "chat":
            return False
            
        # Truncate if too long
        if len(message) > mqtt_config.MQTT_MAX_CHAT_LENGTH:
            message = message[:mqtt_config.MQTT_MAX_CHAT_LENGTH]
            
        topic = f"{mqtt_config.MQTT_TOPIC_CHANNELS}/{channel}"
        data = {
            "type": msg_type,
            "channel": channel,
            "message": message
        }
        rate_limit_key = f"channel_{channel}"
        return self.client.publish(topic, data, rate_limit_key=rate_limit_key)
    
    def publish_data_to_channel(self, channel: str, data_type: str, data_dict: dict) -> bool:
        """
        Publish structured data to a specific channel.
        
        Args:
            channel: Channel name (e.g., "pglok-data")
            data_type: Type of data (e.g., "position", "inventory", "status")
            data_dict: Dictionary of data to publish
            
        Returns:
            True if publish successful
        """
        if not mqtt_config.MQTT_DATA_SHARING_ENABLED:
            return False
            
        topic = f"{mqtt_config.MQTT_TOPIC_CHANNELS}/{channel}"
        data = {
            "type": data_type,
            "channel": channel,
            "data": data_dict
        }
        rate_limit_key = f"channel_data_{channel}_{data_type}"
        return self.client.publish(topic, data, rate_limit_key=rate_limit_key)
