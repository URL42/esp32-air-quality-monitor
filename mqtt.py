# mqtt.py - Optional MQTT publisher
# Publishes readings to Home Assistant or any MQTT broker
# Disable by setting MQTT_ENABLED = False in config.py

import ujson
import config

try:
    from umqtt.simple import MQTTClient
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("[mqtt] umqtt.simple not found - MQTT disabled")


class MQTTPublisher:
    def __init__(self):
        self._client = None
        self._connected = False
        self._last_publish = 0

    def connect(self):
        if not MQTT_AVAILABLE or not config.MQTT_ENABLED:
            return False

        try:
            self._client = MQTTClient(
                client_id=config.MQTT_CLIENT_ID,
                server=config.MQTT_BROKER,
                port=config.MQTT_PORT,
                user=config.MQTT_USER if config.MQTT_USER else None,
                password=config.MQTT_PASSWORD if config.MQTT_PASSWORD else None,
                keepalive=60
            )
            self._client.connect()
            self._connected = True
            print(f"[mqtt] connected to {config.MQTT_BROKER}")

            # Publish Home Assistant MQTT discovery messages
            self._publish_discovery()
            return True

        except Exception as e:
            print(f"[mqtt] connection failed: {e}")
            self._connected = False
            return False

    def _publish_discovery(self):
        """Publish HA MQTT discovery config so sensors appear automatically."""
        prefix = config.MQTT_TOPIC_PREFIX
        device = {
            "identifiers": [config.MQTT_CLIENT_ID],
            "name": "AirCube",
            "model": "AirCube ESP32 + SCD30",
            "manufacturer": "DIY"
        }

        sensors = [
            ("co2",         "CO2",         "ppm",   "carbon_dioxide", None),
            ("temperature", "Temperature", "°C",    "temperature",    "temperature"),
            ("humidity",    "Humidity",    "%",     "humidity",       "humidity"),
        ]

        for slug, name, unit, dev_class, state_class in sensors:
            config_topic = f"homeassistant/sensor/{config.MQTT_CLIENT_ID}/{slug}/config"
            payload = {
                "name": name,
                "state_topic": f"{prefix}/{slug}",
                "unit_of_measurement": unit,
                "device_class": dev_class,
                "unique_id": f"{config.MQTT_CLIENT_ID}_{slug}",
                "device": device
            }
            if state_class:
                payload["state_class"] = "measurement"

            try:
                self._client.publish(
                    config_topic.encode(),
                    ujson.dumps(payload).encode(),
                    retain=True
                )
            except Exception as e:
                print(f"[mqtt] discovery publish failed for {slug}: {e}")

    def publish(self, co2, temperature, humidity, uptime):
        """Publish current readings. Call from main loop."""
        if not self._connected or not config.MQTT_ENABLED:
            return

        import time
        now = time.time()
        if now - self._last_publish < config.MQTT_INTERVAL:
            return

        prefix = config.MQTT_TOPIC_PREFIX
        readings = {
            f"{prefix}/co2":         f"{co2:.1f}",
            f"{prefix}/temperature": f"{temperature:.2f}",
            f"{prefix}/humidity":    f"{humidity:.1f}",
        }

        try:
            for topic, value in readings.items():
                self._client.publish(topic.encode(), value.encode())
            self._last_publish = now
            print(f"[mqtt] published co2={co2:.0f} temp={temperature:.1f} hum={humidity:.1f}")

        except Exception as e:
            print(f"[mqtt] publish error: {e}")
            self._connected = False
            # Will attempt reconnect on next cycle in main.py

    def reconnect(self):
        """Attempt to reconnect after failure."""
        print("[mqtt] attempting reconnect...")
        return self.connect()

    @property
    def connected(self):
        return self._connected
