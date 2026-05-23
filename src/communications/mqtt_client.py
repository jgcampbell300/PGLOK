"""
MQTT Client for PGLOK Communications
Handles connection, publishing, and subscribing to MQTT topics.
"""

import json
import time
import threading
from typing import Callable, Optional, Dict, Any
import paho.mqtt.client as mqtt

import src.config.mqtt_config as mqtt_config


class MqttClient:
    """MQTT client for PGLOK communications."""
    
    def __init__(self, character_name: str):
        """
        Initialize MQTT client.
        
        Args:
            character_name: Player's character name (used for client ID)
        """
        self.character_name = character_name
        self.client_id = f"{mqtt_config.MQTT_CLIENT_ID_PREFIX}_{character_name}_{int(time.time())}"
        self.connected = False
        self.client: Optional[mqtt.Client] = None
        self.message_callbacks: Dict[str, Callable] = {}
        self.last_publish_time: Dict[str, float] = {}
        self._connect_lock = threading.Lock()
        
    def connect(self) -> bool:
        """
        Connect to MQTT broker.
        
        Returns:
            True if connection successful, False otherwise
        """
        if not mqtt_config.MQTT_ENABLED:
            print("MQTT communications disabled in config")
            return False
            
        try:
            self.client = mqtt.Client(client_id=self.client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            
            self.client.connect(
                mqtt_config.MQTT_BROKER_HOST,
                mqtt_config.MQTT_BROKER_PORT,
                mqtt_config.MQTT_KEEPALIVE
            )
            
            self.client.loop_start()
            return True
        except Exception as e:
            print(f"MQTT connection error: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception as e:
                print(f"Disconnect error: {e}")
            finally:
                self.connected = False
    
    def _on_connect(self, client: mqtt.Client, userdata, flags, reason_code, properties):
        """Called when client connects to broker."""
        if reason_code == 0:
            self.connected = True
            print(f"MQTT connected as {self.client_id}")
            
            # Subscribe to topics
            for topic in mqtt_config.MQTT_SUBSCRIPTIONS:
                client.subscribe(topic, qos=mqtt_config.MQTT_QOS)
                print(f"Subscribed to: {topic}")
        else:
            print(f"MQTT connection failed with code {reason_code}")
    
    def _on_disconnect(self, client: mqtt.Client, userdata, disconnect_flags, reason_code, properties):
        """Called when client disconnects from broker."""
        self.connected = False
        print(f"MQTT disconnected: {reason_code}")
    
    def _on_message(self, client: mqtt.Client, userdata, msg):
        """Called when message is received."""
        try:
            # Parse JSON payload
            payload = json.loads(msg.payload.decode())
            
            # Call registered callback for this topic
            topic = msg.topic
            for registered_topic, callback in self.message_callbacks.items():
                if self._topic_matches(topic, registered_topic):
                    callback(topic, payload)
        except json.JSONDecodeError:
            print(f"Invalid JSON received on topic {msg.topic}")
        except Exception as e:
            print(f"Error processing message: {e}")
    
    def _topic_matches(self, topic: str, pattern: str) -> bool:
        """
        Check if topic matches pattern (supports # wildcard).
        
        Args:
            topic: The actual topic
            pattern: The pattern to match (may contain # wildcard)
            
        Returns:
            True if topic matches pattern
        """
        if pattern.endswith("#"):
            base = pattern[:-1]
            return topic.startswith(base)
        return topic == pattern
    
    def publish(self, topic: str, data: Dict[str, Any], rate_limit_key: Optional[str] = None) -> bool:
        """
        Publish data to MQTT topic.
        
        Args:
            topic: MQTT topic to publish to
            data: Dictionary of data to publish (will be JSON encoded)
            rate_limit_key: Key for rate limiting (e.g., 'prices', 'chat')
            
        Returns:
            True if publish successful, False otherwise
        """
        if not self.connected or not mqtt_config.MQTT_ENABLED:
            return False
        
        # Rate limiting
        if rate_limit_key:
            min_interval = mqtt_config.MQTT_MIN_DATA_INTERVAL
            if rate_limit_key == "chat":
                min_interval = mqtt_config.MQTT_MIN_CHAT_INTERVAL
                
            last_time = self.last_publish_time.get(rate_limit_key, 0)
            if time.time() - last_time < min_interval:
                return False
        
        # Add metadata
        data_with_meta = {
            "user": self.character_name,
            "timestamp": int(time.time()),
            **data
        }
        
        # Check message size
        payload = json.dumps(data_with_meta)
        if len(payload) > mqtt_config.MQTT_MAX_MESSAGE_SIZE:
            print(f"Message too large: {len(payload)} bytes (max {mqtt_config.MQTT_MAX_MESSAGE_SIZE})")
            return False
        
        try:
            self.client.publish(topic, payload, qos=mqtt_config.MQTT_QOS)
            if rate_limit_key:
                self.last_publish_time[rate_limit_key] = time.time()
            return True
        except Exception as e:
            print(f"Publish error: {e}")
            return False
    
    def subscribe(self, topic: str, callback: Callable) -> None:
        """
        Subscribe to topic and register callback.
        
        Args:
            topic: Topic to subscribe to
            callback: Function to call when message received (callback(topic, data))
        """
        self.message_callbacks[topic] = callback
        if self.connected:
            self.client.subscribe(topic, qos=mqtt_config.MQTT_QOS)
    
    def unsubscribe(self, topic: str) -> None:
        """
        Unsubscribe from topic.
        
        Args:
            topic: Topic to unsubscribe from
        """
        if topic in self.message_callbacks:
            del self.message_callbacks[topic]
        if self.connected:
            self.client.unsubscribe(topic)
