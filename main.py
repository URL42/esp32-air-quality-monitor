# main.py - AirCube main application
# Coordinates sensor, LED, web server, and optional MQTT

import time
import network
import ujson
import uasyncio as asyncio
from machine import I2C, Pin
from collections import deque

import config
from scd30 import SCD30, SCD30Error
from led import AirLED
from web import WebServer
from mqtt import MQTTPublisher


# ------------------------------------------------------------------ #
#  Shared data store                                                  #
# ------------------------------------------------------------------ #

class DataStore:
    """Thread-safe-ish store for current readings + rolling history."""

    def __init__(self):
        self.co2 = 0.0
        self.temperature = 0.0
        self.humidity = 0.0
        self.ready = False
        self.uptime = 0
        # Rolling history: deque of {t, c, temp, hum}
        self._history = deque((), config.HISTORY_SIZE)

    @staticmethod
    def c_to_f(c):
        return c * 9 / 5 + 32

    def update(self, co2, temperature, humidity, uptime):
        self.co2 = co2
        self.temperature = temperature          # always stored as °C internally
        self.humidity = humidity
        self.uptime = uptime
        self.ready = True

        # Store compact history point with HH:MM timestamp
        t = time.localtime(time.time())
        label = "{:02d}:{:02d}".format(t[3], t[4])
        self._history.append({
            "t":    label,
            "c":    round(co2, 1),
            "temp": round(self.c_to_f(temperature), 1),  # °F in history
            "hum":  round(humidity, 1)
        })

    def to_json(self):
        return ujson.dumps({
            "co2":         round(self.co2, 1),
            "temperature": round(self.c_to_f(self.temperature), 2),  # °F
            "humidity":    round(self.humidity, 1),
            "uptime":      self.uptime,
            "ready":       self.ready,
            "history":     list(self._history)
        })


# ------------------------------------------------------------------ #
#  WiFi                                                               #
# ------------------------------------------------------------------ #

def connect_wifi(led):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        print(f"[wifi] already connected: {wlan.ifconfig()[0]}")
        return wlan

    print(f"[wifi] connecting to {config.WIFI_SSID}...")
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)

    led.pulse_blue(times=1, delay_ms=100)

    deadline = time.time() + config.WIFI_TIMEOUT
    while not wlan.isconnected():
        if time.time() > deadline:
            print("[wifi] connection timed out")
            return None
        time.sleep_ms(500)
        print(".", end="")

    ip = wlan.ifconfig()[0]
    print(f"\n[wifi] connected — http://{ip}")
    return wlan


# ------------------------------------------------------------------ #
#  Sensor task                                                        #
# ------------------------------------------------------------------ #

async def sensor_task(sensor, led, data_store, mqtt):
    """Reads SCD30 and updates LED + data store. Runs every second."""
    start_time = time.time()
    warmup_done = False
    WARMUP_SEC = 180  # 3 minutes

    led.set_warming_up()
    print("[sensor] warming up (3 min)...")

    while True:
        uptime = time.time() - start_time

        # Warmup indicator
        if not warmup_done:
            if uptime >= WARMUP_SEC:
                warmup_done = True
                print("[sensor] warm-up complete")
            else:
                remaining = WARMUP_SEC - uptime
                if int(remaining) % 30 == 0:
                    print(f"[sensor] warming up... {int(remaining)}s remaining")

        try:
            result = sensor.read_measurement()
            if result is not None:
                co2, temp, hum = result

                # Clamp obviously bad readings during warmup
                if not warmup_done and co2 < 400:
                    await asyncio.sleep(1)
                    continue

                data_store.update(co2, temp, hum, int(uptime))

                if warmup_done:
                    led.set_co2(co2)

                # MQTT publish (rate-limited internally)
                if config.MQTT_ENABLED:
                    if not mqtt.connected:
                        mqtt.reconnect()
                    mqtt.publish(co2, temp, hum, int(uptime))

                temp_f = temp * 9 / 5 + 32
                print(f"[sensor] CO2={co2:.0f}ppm  T={temp_f:.1f}°F  RH={hum:.1f}%")

        except SCD30Error as e:
            print(f"[sensor] error: {e}")
            led.set_error()
            await asyncio.sleep(5)
            continue

        await asyncio.sleep(config.SCD30_INTERVAL)


# ------------------------------------------------------------------ #
#  Button task (optional)                                             #
# ------------------------------------------------------------------ #

async def button_task(led):
    """
    Optional: wire a button to GPIO0 (or change BUTTON_PIN in config).
    Short press cycles brightness.
    """
    BUTTON_PIN = getattr(config, 'BUTTON_PIN', None)
    if BUTTON_PIN is None:
        return  # No button configured

    btn = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)
    last_state = 1
    press_time = 0

    while True:
        state = btn.value()
        now = time.ticks_ms()

        if last_state == 1 and state == 0:
            # Button pressed
            press_time = now

        elif last_state == 0 and state == 1:
            # Button released
            duration = time.ticks_diff(now, press_time)
            if duration < 1000:
                led.cycle_brightness()
                print(f"[button] brightness -> {led.brightness:.0%}")

        last_state = state
        await asyncio.sleep_ms(50)


# ------------------------------------------------------------------ #
#  Main                                                               #
# ------------------------------------------------------------------ #

async def main():
    print("\n=== AirCube starting ===")

    # --- LED init ---
    led = AirLED()
    led.pulse_blue(times=2, delay_ms=150)

    # --- WiFi ---
    wlan = connect_wifi(led)
    if wlan is None:
        print("[wifi] running without network — web UI unavailable")

    # --- SCD30 init ---
    print("[sensor] initialising SCD30...")
    try:
        i2c = I2C(0, sda=Pin(config.SCD30_SDA), scl=Pin(config.SCD30_SCL), freq=50000)
        sensor = SCD30(i2c)

        fw = sensor.get_firmware_version()
        print(f"[sensor] SCD30 firmware {fw[0]}.{fw[1]}")

        sensor.set_measurement_interval(config.SCD30_INTERVAL)
        sensor.set_auto_calibration(config.SCD30_AUTO_CALIBRATE)

        if config.SCD30_ALTITUDE > 0:
            sensor.set_altitude(config.SCD30_ALTITUDE)
            print(f"[sensor] altitude compensation: {config.SCD30_ALTITUDE}m")

        sensor.start_continuous(
            pressure_mbar=config.SCD30_PRESSURE if config.SCD30_PRESSURE > 0 else 0
        )
        print("[sensor] continuous measurement started")

    except SCD30Error as e:
        print(f"[sensor] FATAL: {e}")
        led.set_error()
        # Halt — can't run without sensor
        while True:
            await asyncio.sleep(1)

    # --- Data store ---
    data_store = DataStore()

    # --- MQTT ---
    mqtt = MQTTPublisher()
    if config.MQTT_ENABLED:
        mqtt.connect()

    # --- Web server ---
    web = WebServer(data_store)

    # --- Run tasks concurrently ---
    tasks = [
        asyncio.create_task(sensor_task(sensor, led, data_store, mqtt)),
        asyncio.create_task(button_task(led)),
    ]

    if wlan and wlan.isconnected():
        tasks.append(asyncio.create_task(web.start()))
        ip = wlan.ifconfig()[0]
        print(f"[web] dashboard at http://{ip}")

    print("=== AirCube running ===\n")
    await asyncio.gather(*tasks)


# Entry point
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\n[main] stopped by user")
