# scd30.py - Sensirion SCD30 MicroPython driver
# Handles I2C communication, CRC, and all sensor commands

import time
import struct
from machine import I2C

SCD30_ADDR = 0x61

# Commands
CMD_START_CONTINUOUS   = b'\x00\x10'
CMD_STOP_CONTINUOUS    = b'\x01\x04'
CMD_SET_INTERVAL       = b'\x46\x00'
CMD_DATA_READY         = b'\x02\x02'
CMD_READ_MEASUREMENT   = b'\x03\x00'
CMD_AUTO_CALIBRATION   = b'\x53\x06'
CMD_SET_ALTITUDE       = b'\x51\x02'
CMD_SET_PRESSURE       = b'\x00\x10'  # same as start, pressure is arg
CMD_SOFT_RESET         = b'\xD3\x04'
CMD_FIRMWARE_VERSION   = b'\xD1\x00'


def _crc8(data):
    """CRC-8 checksum: poly 0x31, init 0xFF"""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ 0x31
            else:
                crc <<= 1
            crc &= 0xFF
    return crc


def _pack_word_with_crc(value):
    """Pack a uint16 as two bytes + CRC."""
    msb = (value >> 8) & 0xFF
    lsb = value & 0xFF
    return bytes([msb, lsb, _crc8([msb, lsb])])


class SCD30Error(Exception):
    pass


class SCD30:
    def __init__(self, i2c, addr=SCD30_ADDR):
        self._i2c = i2c
        self._addr = addr
        self._co2 = None
        self._temperature = None
        self._humidity = None

        # Verify sensor is present
        devices = self._i2c.scan()
        if self._addr not in devices:
            raise SCD30Error(f"SCD30 not found on I2C bus (found: {devices})")

    # ------------------------------------------------------------------ #
    #  Low-level I2C helpers                                               #
    # ------------------------------------------------------------------ #

    def _send_cmd(self, cmd, arg=None):
        """Send a command with optional uint16 argument."""
        buf = bytearray(cmd)
        if arg is not None:
            buf += _pack_word_with_crc(arg)
        self._i2c.writeto(self._addr, buf)
        time.sleep_ms(3)

    def _read_response(self, n_words):
        """Read n_words (each 2 bytes + 1 CRC byte) and return list of uint16."""
        raw = self._i2c.readfrom(self._addr, n_words * 3)
        result = []
        for i in range(n_words):
            msb = raw[i * 3]
            lsb = raw[i * 3 + 1]
            crc = raw[i * 3 + 2]
            if _crc8([msb, lsb]) != crc:
                raise SCD30Error(f"CRC mismatch at word {i}")
            result.append((msb << 8) | lsb)
        return result

    # ------------------------------------------------------------------ #
    #  Sensor control                                                      #
    # ------------------------------------------------------------------ #

    def soft_reset(self):
        self._send_cmd(CMD_SOFT_RESET)
        time.sleep_ms(100)

    def start_continuous(self, pressure_mbar=0):
        """Start continuous measurement. Pass ambient pressure (mbar) for compensation."""
        self._send_cmd(CMD_START_CONTINUOUS, pressure_mbar)

    def stop_continuous(self):
        self._send_cmd(CMD_STOP_CONTINUOUS)

    def set_measurement_interval(self, interval_sec):
        """Set measurement interval in seconds (2-1800)."""
        if not 2 <= interval_sec <= 1800:
            raise ValueError("Interval must be 2-1800 seconds")
        self._send_cmd(CMD_SET_INTERVAL, interval_sec)

    def set_auto_calibration(self, enabled):
        """Enable or disable automatic self-calibration (ASC)."""
        self._send_cmd(CMD_AUTO_CALIBRATION, 1 if enabled else 0)

    def set_altitude(self, altitude_m):
        """Set altitude compensation in meters."""
        self._send_cmd(CMD_SET_ALTITUDE, altitude_m)

    def get_firmware_version(self):
        self._send_cmd(CMD_FIRMWARE_VERSION)
        time.sleep_ms(3)
        words = self._read_response(1)
        major = (words[0] >> 8) & 0xFF
        minor = words[0] & 0xFF
        return major, minor

    # ------------------------------------------------------------------ #
    #  Reading data                                                        #
    # ------------------------------------------------------------------ #

    def data_ready(self):
        """Returns True if a new measurement is available."""
        self._send_cmd(CMD_DATA_READY)
        time.sleep_ms(3)
        words = self._read_response(1)
        return bool(words[0])

    def read_measurement(self):
        """
        Read CO2, temperature, humidity.
        Returns (co2_ppm, temp_c, humidity_rh) or None if not ready.
        """
        if not self.data_ready():
            return None

        self._send_cmd(CMD_READ_MEASUREMENT)
        time.sleep_ms(3)
        words = self._read_response(6)

        # Each value is two uint16 words forming an IEEE 754 float
        def words_to_float(high, low):
            raw = struct.pack('>HH', high, low)
            return struct.unpack('>f', raw)[0]

        co2  = words_to_float(words[0], words[1])
        temp = words_to_float(words[2], words[3])
        hum  = words_to_float(words[4], words[5])

        self._co2 = co2
        self._temperature = temp
        self._humidity = hum

        return co2, temp, hum

    # ------------------------------------------------------------------ #
    #  Convenience properties (last read values)                          #
    # ------------------------------------------------------------------ #

    @property
    def co2(self):
        return self._co2

    @property
    def temperature(self):
        return self._temperature

    @property
    def humidity(self):
        return self._humidity
