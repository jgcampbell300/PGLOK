"""
PGLOK Communications Module
Handles MQTT-based real-time communications for chat, data sharing, and presence.
"""

__all__ = ["MqttClient", "DataPublisher", "DataListener", "CommunicationsWindow"]


def __getattr__(name):
    if name == "MqttClient":
        from .mqtt_client import MqttClient
        return MqttClient
    if name == "DataPublisher":
        from .data_publisher import DataPublisher
        return DataPublisher
    if name == "DataListener":
        from .data_listener import DataListener
        return DataListener
    if name == "CommunicationsWindow":
        from .communications_window import CommunicationsWindow
        return CommunicationsWindow
    raise AttributeError(f"module 'src.communications' has no attribute '{name}'")
