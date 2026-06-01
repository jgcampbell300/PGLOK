"""
MQTT Configuration for PGLOK Communications
"""

# MQTT Broker Settings
MQTT_BROKER_HOST = "broker.hivemq.com"  # Free public broker
MQTT_BROKER_PORT = 1883  # Unencrypted (use 8883 for SSL/TLS)
MQTT_KEEPALIVE = 60  # Seconds
MQTT_QOS = 1  # Quality of Service: 0=at most once, 1=at least once, 2=exactly once

# Topic Structure
MQTT_BASE_TOPIC = "pglok"
MQTT_TOPIC_CHAT = f"{MQTT_BASE_TOPIC}/chat"
MQTT_TOPIC_PRICES = f"{MQTT_BASE_TOPIC}/data/prices"
MQTT_TOPIC_FAVOR = f"{MQTT_BASE_TOPIC}/data/favor"
MQTT_TOPIC_PRESENCE = f"{MQTT_BASE_TOPIC}/presence"
MQTT_TOPIC_CHANNELS = f"{MQTT_BASE_TOPIC}/channels"

# Default channels
DEFAULT_CHANNELS = ["general", "pglok-data"]

# Subscribe to all data topics and channel topics
MQTT_SUBSCRIPTIONS = [
    MQTT_TOPIC_CHAT,
    f"{MQTT_BASE_TOPIC}/data/#",  # All data subtopics
    MQTT_TOPIC_PRESENCE,
    f"{MQTT_TOPIC_CHANNELS}/#",  # All channel topics
]

# Rate Limiting
MQTT_MIN_DATA_INTERVAL = 30  # Seconds between automated data publishes
MQTT_MIN_CHAT_INTERVAL = 2  # Seconds between chat messages per user
MQTT_PRESENCE_INTERVAL = 60  # Seconds between presence heartbeats

# Message Limits
MQTT_MAX_MESSAGE_SIZE = 1024  # 1KB max message size
MQTT_MAX_CHAT_LENGTH = 500  # Max chat message characters

# Presence Settings
MQTT_PRESENCE_TIMEOUT = 180  # Seconds before user considered offline (3 minutes)

# Connection Settings
MQTT_RECONNECT_DELAY = 5  # Seconds between reconnection attempts
MQTT_MAX_RECONNECT_ATTEMPTS = 10  # Maximum reconnection attempts before giving up

# Enable/Disable Communications
MQTT_ENABLED = True  # Global toggle for all MQTT communications
MQTT_CHAT_ENABLED = True  # Toggle for chat specifically
MQTT_DATA_SHARING_ENABLED = True  # Toggle for data sharing

# User Identification
# Each client should use: pglok_{character_name}_{timestamp}
MQTT_CLIENT_ID_PREFIX = "pglok"
