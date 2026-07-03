# ESP32 + SCD30 Air Quality Monitor

## Hardware

| Component | Notes |
|-----------|-------|
| ESP32 (any variant) | Dev board or bare module |
| Sensirion SCD30 | Real NDIR CO2 + temp + humidity |
| WS2812B (1x) | Bare square module works fine |

## Wiring

### SCD30 → ESP32
```
SCD30 VIN  → 3.3V
SCD30 GND  → GND
SCD30 SDA  → GPIO 21  (config: SCD30_SDA)
SCD30 SCL  → GPIO 22  (config: SCD30_SCL)
SCD30 RDY  → not required (polling mode)
```
> ⚠️ SCD30 is 3.3V only — do not connect to 5V.
> Use 4.7kΩ pull-up resistors on SDA/SCL if you have signal issues.

### WS2812B → ESP32
```
WS2812B VCC → 3.3V  (or 5V from USB — brighter, but 3.3V works for 1 LED)
WS2812B GND → GND
WS2812B DIN → GPIO 5  (config: LED_PIN)
```
> Tip: A 300-500Ω resistor inline on the data line prevents ringing.

### Optional button
```
Button → GPIO 0 → GND  (add BUTTON_PIN = 0 to config.py)
```
GPIO 0 already has an internal pull-up. Short press cycles LED brightness.

## I2C Frequency Note
The SCD30 is slow — `freq=50000` (50kHz) is used intentionally.
Don't bump this up; it causes read errors.

## Setup

### 1. Flash MicroPython
Download the latest MicroPython .bin for your ESP32 from https://micropython.org/download/

```bash
pip install esptool
esptool.py --chip esp32 erase_flash
esptool.py --chip esp32 --baud 460800 write_flash -z 0x1000 micropython.bin
```

### 2. Install files
Using mpremote (recommended):
```bash
pip install mpremote
mpremote connect /dev/ttyUSB0 cp boot.py :
mpremote connect /dev/ttyUSB0 cp config.py :
mpremote connect /dev/ttyUSB0 cp scd30.py :
mpremote connect /dev/ttyUSB0 cp led.py :
mpremote connect /dev/ttyUSB0 cp web.py :
mpremote connect /dev/ttyUSB0 cp mqtt.py :
mpremote connect /dev/ttyUSB0 cp main.py :
```

Or use Thonny — open each file and save to device.

### 3. Edit config.py
At minimum set:
```python
WIFI_SSID = "your_network"
WIFI_PASSWORD = "your_password"
```

### 4. Run
Reset the ESP32. Watch serial output for the IP address:
```
[wifi] connected — http://192.168.1.xxx
[web] dashboard at http://192.168.1.xxx
```
Open that URL in a browser.

## Home Assistant

### Option A: MQTT (set MQTT_ENABLED = True in config.py)
AirCube auto-publishes HA discovery messages. Sensors appear automatically
under Settings → Devices once the MQTT integration is configured.

Topics:
- `aircube/co2`
- `aircube/temperature`
- `aircube/humidity`

### Option B: REST sensor (no MQTT needed)
Add to `configuration.yaml`:
```yaml
sensor:
  - platform: rest
    name: AirCube CO2
    resource: http://192.168.1.xxx/data
    value_template: "{{ value_json.co2 }}"
    unit_of_measurement: ppm
    scan_interval: 30

  - platform: rest
    name: AirCube Temperature
    resource: http://192.168.1.xxx/data
    value_template: "{{ value_json.temperature }}"
    unit_of_measurement: "°C"
    scan_interval: 30

  - platform: rest
    name: AirCube Humidity
    resource: http://192.168.1.xxx/data
    value_template: "{{ value_json.humidity }}"
    unit_of_measurement: "%"
    scan_interval: 30
```

## LED Colors

| Color | CO2 | Meaning |
|-------|-----|---------|
| Green | < 600 ppm | Excellent |
| Yellow-green | 600–800 ppm | Good |
| Yellow | 800–1000 ppm | Fair |
| Orange | 1000–1500 ppm | Poor |
| Red | > 1500 ppm | Bad — ventilate |

Thresholds are fully configurable in `config.py`.

## SCD30 Notes

- **3-minute warm-up** on every power-on — LED stays dim white during this
- **1-hour initial conditioning** on first ever power-on — readings stabilize slowly
- **Auto-calibration** assumes the sensor sees outdoor-level CO2 (~400ppm) at
  least once every 7 days. Disable with `SCD30_AUTO_CALIBRATE = False` if
  the device lives in a sealed room.
- For best accuracy set `SCD30_ALTITUDE` to your elevation in meters.
