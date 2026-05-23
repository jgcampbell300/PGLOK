"""
Data Publisher for PGLOK Communications
Provides functions to publish different types of game data via MQTT.
"""

import src.config.mqtt_config as mqtt_config
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
