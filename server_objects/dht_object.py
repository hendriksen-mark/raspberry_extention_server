"""
DHT sensor service for temperature and humidity monitoring
"""
from threading import Lock
import logging
from typing import Any, Callable, cast
from time import sleep

import logManager

try:
    import adafruit_dht
    import board
except (ImportError, RuntimeError):
    from services.dummy_import import DummyDHT as adafruit_dht
    from services.dummy_import import DummyBoard as board

logger: logging.Logger = logManager.logger.get_logger(__name__)

TemperatureCallback = Callable[[float], None]
HumidityCallback = Callable[[float], None]

class DHTObject:
    """
    DHT sensor service for reading temperature and humidity
    """
    def __init__(self, data: dict[str, Any]) -> None:
        self.sensor_type: str = data.get("sensor_type", "DHT22").upper()
        if self.sensor_type not in ["DHT22", "DHT11"]:
            logger.error(f"Unsupported DHT sensor type: {self.sensor_type}. Defaulting to DHT22.")
            self.sensor_type = "DHT22"

        raw_dht_pin = data.get("dht_pin", None)
        try:
            self.dht_pin: int | None = int(raw_dht_pin) if raw_dht_pin is not None else None
        except (TypeError, ValueError):
            logger.error(f"Invalid dht_pin value: {raw_dht_pin}. Using None.")
            self.dht_pin = None

        self.latest_temperature: float | None = cast(float | None, data.get("latest_temperature"))
        self.latest_humidity: float | None = cast(float | None, data.get("latest_humidity"))
        self.temperature_callbacks: list[TemperatureCallback] = []
        self.humidity_callbacks: list[HumidityCallback] = []
        self.min_dht_temp: float = data.get("MIN_DHT_TEMP", -40.0)
        self.max_dht_temp: float = data.get("MAX_DHT_TEMP", 80.0)
        self.min_humidity: float = data.get("MIN_HUMIDITY", 0.0)
        self.max_humidity: float = data.get("MAX_HUMIDITY", 100.0)
        self.dht_temp_change_threshold: float = data.get("DHT_TEMP_CHANGE_THRESHOLD", 0.5)
        self.dht_humidity_change_threshold: float = data.get("DHT_HUMIDITY_CHANGE_THRESHOLD", 5.0)
        self.dht_lock = Lock()
        self.last_logged_dht_temp: float | None = None
        self.last_logged_dht_humidity: float | None = None
        self._thread_started = False
        self.dht_device: Any

        # Get the pin from board using the pin number and Dynamically create the DHT sensor based on sensor type
        pin: Any | None = None
        try:
            if self.dht_pin is None:
                raise ValueError("dht_pin is required to initialize the DHT sensor")
            pin = getattr(board, f"D{self.dht_pin}")
            sensor_pin: Any = cast(Any, pin)
            if self.sensor_type == "DHT22":
                self.dht_device = adafruit_dht.DHT22(sensor_pin)
            elif self.sensor_type == "DHT11":
                self.dht_device = adafruit_dht.DHT11(sensor_pin)
            elif self.sensor_type == "DHT21":
                self.dht_device = adafruit_dht.DHT21(sensor_pin)
            else:
                # Fallback to DHT22 if sensor type is not recognized
                logger.warning(f"Unknown sensor type {self.sensor_type}, defaulting to DHT22")
                self.dht_device = adafruit_dht.DHT22(sensor_pin)
            if hasattr(self.dht_device, "is_dummy") and self.dht_device.is_dummy():
                return
            logger.debug(f"DHT{self.sensor_type} sensor initialized on pin D{self.dht_pin}")
        except (AttributeError, NotImplementedError, RuntimeError, OSError, ValueError) as e:
            logger.error(f"Failed to initialize DHT sensor: {e}")
            logger.warning("Using DummyDHT")
            self.dht_device = adafruit_dht.DHT22(cast(Any, pin))

    def get_pin(self) -> int | None:
        """Get current DHT pin"""
        return self.dht_pin

    def get_data(self) -> tuple[float | None, float | None]:
        """Get current temperature and humidity data"""
        with self.dht_lock:
            return self.latest_temperature, self.latest_humidity

    def register_temperature_callback(self, callback: TemperatureCallback) -> None:
        """Register a callback function to be called when temperature changes significantly"""
        self.temperature_callbacks.append(callback)

    def register_humidity_callback(self, callback: HumidityCallback) -> None:
        """Register a callback function to be called when humidity changes significantly"""
        self.humidity_callbacks.append(callback)

    def _notify_temperature_callbacks(self, temperature: float) -> None:
        """Notify all registered temperature callbacks"""
        for callback in self.temperature_callbacks:
            try:
                callback(temperature)
            except (RuntimeError, TypeError, AttributeError) as e:
                logger.error(f"Error in temperature callback: {e}")

    def _notify_humidity_callbacks(self, humidity: float) -> None:
        """Notify all registered humidity callbacks"""
        for callback in self.humidity_callbacks:
            try:
                callback(humidity)
            except (RuntimeError, TypeError, AttributeError) as e:
                logger.error(f"Error in humidity callback: {e}")

    def read_dht_temperature(self) -> None:
        """
        Read the temperature and humidity from the DHT sensor once
        and update the global variables.
        If the sensor returns invalid values (None or out of range), do not update globals.
        """

        # DHT sensors often fail on first attempt, so we retry
        max_retries = 3
        temperature = None
        humidity = None

        for attempt in range(max_retries):
            try:
                temperature = self.dht_device.temperature
                humidity = self.dht_device.humidity

                # If we got valid readings, break out of retry loop
                if temperature is not None and humidity is not None:
                    if attempt != 0:
                        logger.debug(f"DHT read successful on attempt {attempt + 1}")
                    break

            except (RuntimeError, OSError) as e:
                error_str = str(e).lower()
                # These are normal DHT sensor errors that should trigger a retry
                if ("checksum did not validate" in error_str or
                    "full buffer was not returned" in error_str or
                    "try again" in error_str):
                    if attempt < max_retries - 1:
                        logger.debug(f"DHT read attempt {attempt + 1} failed (normal), retrying...")
                        sleep(0.1)  # Small delay before retry
                        continue
                    logger.debug(f"DHT sensor failed after {max_retries} attempts: {e}")
                    return

                # For other errors, don't retry
                logger.error(f"Error reading DHT sensor: {e}")
                return

        # Process the readings if we got them
        if temperature is None and humidity is None:
            logger.debug("No valid DHT readings obtained after retries")
            return

        logger.debug(f"Raw DHT read: temperature={temperature}, humidity={humidity}")

        with self.dht_lock:
            # Only update if values are valid
            if temperature is not None and self.min_dht_temp < temperature < self.max_dht_temp:
                rounded_temp: float = round(float(temperature), 1)
                logged_info = False
                if self.latest_temperature != rounded_temp:
                    self.latest_temperature = rounded_temp
                    # Only log when temperature changes significantly or this is the first reading
                    if (self.last_logged_dht_temp is None or
                        abs(rounded_temp - self.last_logged_dht_temp) >= self.dht_temp_change_threshold):
                        logger.info(f"Updated temperature: {self.latest_temperature}°C")
                        self.last_logged_dht_temp = rounded_temp
                        # Notify callbacks about temperature change
                        self._notify_temperature_callbacks(rounded_temp)
                        logged_info = True

                # Always log current temperature for debugging (unless we just logged at info level)
                if not logged_info:
                    logger.debug(f"Temperature: {rounded_temp}°C")
            else:
                logger.error("Temperature value not updated (None or out of range)")

            if humidity is not None and self.min_humidity <= humidity <= self.max_humidity:
                rounded_humidity: float = round(float(humidity), 1)
                logged_info = False
                if self.latest_humidity != rounded_humidity:
                    self.latest_humidity = rounded_humidity
                    # Only log when humidity changes significantly or this is the first reading
                    if (self.last_logged_dht_humidity is None or
                        abs(rounded_humidity - self.last_logged_dht_humidity) >= self.dht_humidity_change_threshold):
                        logger.info(f"Updated humidity: {self.latest_humidity}%")
                        self.last_logged_dht_humidity = rounded_humidity
                        # Notify callbacks about humidity change
                        self._notify_humidity_callbacks(rounded_humidity)
                        logged_info = True

                # Always log current humidity for debugging (unless we just logged at info level)
                if not logged_info:
                    logger.debug(f"Humidity: {rounded_humidity}%")
            else:
                logger.error("Humidity value not updated (None or out of range)")

    def get_all_data(self) -> dict[str, Any]:
        """Get all DHT data as a dictionary"""
        with self.dht_lock:
            return {
                "sensor_type": self.sensor_type,
                "dht_pin": self.dht_pin,
                "latest_temperature": self.latest_temperature,
                "latest_humidity": self.latest_humidity,
                "MIN_DHT_TEMP": self.min_dht_temp,
                "MAX_DHT_TEMP": self.max_dht_temp,
                "MIN_HUMIDITY": self.min_humidity,
                "MAX_HUMIDITY": self.max_humidity,
                "DHT_TEMP_CHANGE_THRESHOLD": self.dht_temp_change_threshold,
                "DHT_HUMIDITY_CHANGE_THRESHOLD": self.dht_humidity_change_threshold
            }

    def save(self) -> dict[str, Any]:
        """Save current DHT state to a dictionary"""
        return self.get_all_data()
