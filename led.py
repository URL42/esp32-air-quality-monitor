# led.py - WS2812B LED controller
# Handles color mapping from CO2 readings + brightness control

import neopixel
from machine import Pin
import config


class AirLED:
    def __init__(self):
        pin = Pin(config.LED_PIN, Pin.OUT)
        self._np = neopixel.NeoPixel(pin, config.LED_COUNT)
        self._brightness = config.LED_BRIGHTNESS
        self._current_rgb = (0, 0, 0)
        self.off()

    # ------------------------------------------------------------------ #
    #  Brightness                                                          #
    # ------------------------------------------------------------------ #

    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, value):
        self._brightness = max(0.0, min(1.0, value))
        # Re-apply current color at new brightness
        self._apply(self._current_rgb)

    def cycle_brightness(self):
        """Cycle through preset brightness levels (like AirCube button press)."""
        levels = [0.0, 0.1, 0.3, 0.6, 1.0]
        current = self._brightness
        # Find next level
        for i, lvl in enumerate(levels):
            if abs(current - lvl) < 0.05:
                self._brightness = levels[(i + 1) % len(levels)]
                self._apply(self._current_rgb)
                return
        # Fallback
        self._brightness = 0.3
        self._apply(self._current_rgb)

    # ------------------------------------------------------------------ #
    #  Color control                                                       #
    # ------------------------------------------------------------------ #

    def _apply(self, rgb):
        """Write RGB tuple to NeoPixel, scaled by brightness."""
        self._current_rgb = rgb
        r = int(rgb[0] * self._brightness)
        g = int(rgb[1] * self._brightness)
        b = int(rgb[2] * self._brightness)
        self._np[0] = (r, g, b)
        self._np.write()

    def off(self):
        self._apply((0, 0, 0))

    def set_color(self, r, g, b):
        self._apply((r, g, b))

    def set_co2(self, co2_ppm):
        """
        Map a CO2 reading to an LED color using thresholds from config.
        Smoothly interpolates between threshold colors.
        """
        thresholds = config.CO2_THRESHOLDS

        # Below first threshold
        if co2_ppm <= thresholds[0][0]:
            self._apply(thresholds[0][1])
            return

        # Above last threshold
        if co2_ppm >= thresholds[-1][0]:
            self._apply(thresholds[-1][1])
            return

        # Interpolate between two surrounding thresholds
        for i in range(len(thresholds) - 1):
            low_ppm,  low_color  = thresholds[i]
            high_ppm, high_color = thresholds[i + 1]

            if low_ppm <= co2_ppm <= high_ppm:
                t = (co2_ppm - low_ppm) / (high_ppm - low_ppm)
                r = int(low_color[0] + t * (high_color[0] - low_color[0]))
                g = int(low_color[1] + t * (high_color[1] - low_color[1]))
                b = int(low_color[2] + t * (high_color[2] - low_color[2]))
                self._apply((r, g, b))
                return

    def pulse_blue(self, times=3, delay_ms=200):
        """Blue pulse - used for WiFi connecting status."""
        for _ in range(times):
            self._apply((0, 0, 255))
            import time
            time.sleep_ms(delay_ms)
            self.off()
            time.sleep_ms(delay_ms)
        # Restore
        self._apply(self._current_rgb)

    def set_warming_up(self):
        """Dim white while sensor warms up."""
        self._apply((80, 80, 80))

    def set_error(self):
        """Slow red blink to indicate a hardware error."""
        self._apply((255, 0, 0))
