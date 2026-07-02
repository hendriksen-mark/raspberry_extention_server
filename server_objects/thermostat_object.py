"""
Thermostat service for managing thermostat operations
"""
import asyncio
from time import localtime, strftime
from typing import Any, TypedDict, cast
import logging

from bleak.exc import BleakError

from eqiva_thermostat import Thermostat, Temperature, EqivaException
import logManager

logger: logging.Logger = logManager.logger.get_logger(__name__)


class HeatingCoolingState(TypedDict):
    """Represents the heating/cooling state of the thermostat"""
    int: int
    str: str


class ThermostatObject:
    """Service for managing thermostat operations"""

    def __init__(self, data: dict[str, Any]) -> None:
        self.id: str = str(data.get("id") or "")  # Unique identifier for the thermostat
        self.mac: str = str(data.get("mac") or "")  # MAC address of the thermostat
        self.failed_connection: bool = True  # Track failed connection
        self.target_heating_cooling_state: int = data.get("targetHeatingCoolingState", 0)  # Default target state
        self.target_temperature: float = data.get("targetTemperature", 0.0)  # Default target temperature
        self.current_heating_cooling_state: int = data.get("currentHeatingCoolingState", 0)  # Default current state
        self.current_temperature: float = data.get("currentTemperature", 0.0)  # Default DHT temperature
        self.current_relative_humidity: float = data.get("currentRelativeHumidity", 0.0)  # Default DHT humidity
        self.last_updated: str | None = data.get("last_updated")  # Last update timestamp
        self.first_seen: str = data.get("first_seen", strftime("%Y-%m-%d %H:%M:%S", localtime()))
        self.equiva_thermostat: Thermostat = Thermostat(self.mac)
        self.min_temperature = data.get("min_temperature", 5.0)  # Minimum temperature setting
        self.max_temperature = data.get("max_temperature", 30.0)  # Maximum
        self.dht_connected: bool = False  # DHT connection status

    def calculate_heating_cooling_state(self, mode: list[str], valve: int | None = None) -> HeatingCoolingState:
        """
        Calculate the current heating/cooling state based on mode and valve position
        Possible return values:
        0 - Off
        1 - Heating
        2 - Cooling (not used in this context)
        3 - Auto
        """
        # Determine the state based on mode and valve
        if valve is not None:
            if 'OFF' in mode or (valve is not None and valve <= 0):
                return {"int": 0, "str": "Off"}  # Off
            if valve and valve > 0:
                return {"int": 1, "str": "Heating"}  # Heating
            return {"int": 0, "str": "Off"}  # Off
        if valve is None:
            if 'AUTO' in mode:
                return {"int": 3, "str": "Auto"}  # Auto mode
            if 'MANUAL' in mode:
                return {"int": 1, "str": "Manual"}  # Manual mode
            return {"int": 0, "str": "Off"}  # Off
        return {"int": 0, "str": "Off"}  # Default

    def update_dht_related_status(self, **kwargs) -> None:
        """Update DHT-related status for all MAC addresses"""
        if not self.dht_connected:
            self.dht_connected = True

        current_temp = cast(float | None, kwargs.get('temperature'))
        current_hum = cast(float | None, kwargs.get('humidity'))
        if current_temp is not None:
            self.current_temperature = current_temp
        if current_hum is not None:
            self.current_relative_humidity = current_hum

        logger.debug(
            f"Updated DHT status for {self.mac} "
            f"thermostat: temp={self.current_temperature}°C, humidity={self.current_relative_humidity}%")

    def get_status(self) -> dict[str, Any]:
        """Get thermostat status for a given MAC address"""
        response: dict[str, Any] = {
            "targetHeatingCoolingState": self.target_heating_cooling_state,
            "targetTemperature": self.target_temperature,
            "currentHeatingCoolingState": self.current_heating_cooling_state,
            "currentTemperature": self.target_temperature
        }

        if self.dht_connected:
            response["currentRelativeHumidity"] = self.current_relative_humidity
            response["currentTemperature"] = self.current_temperature

        return response

    async def safe_connect(self) -> None:
        """Safely connect to thermostat"""
        try:
            await self.equiva_thermostat.connect()
            # Connection successful, reset failed connection flag
            if self.failed_connection:
                logger.info(f"Connection recovered for {self.mac}")
                self.failed_connection = False
        except (BleakError, EqivaException, RuntimeError, OSError) as e:
            logger.error(f"Failed to connect to {self.mac}: {e}")
            self.failed_connection = True
            raise

    async def safe_disconnect(self) -> None:
        """Safely disconnect from thermostat"""
        try:
            await self.equiva_thermostat.disconnect()
        except (TimeoutError, asyncio.CancelledError) as e:
            logger.warning(f"Disconnect timeout/cancelled for {self.equiva_thermostat.address}: {e}")
        except (BleakError, EqivaException, RuntimeError, OSError) as e:
            logger.error(f"Error disconnecting from {self.equiva_thermostat.address}: {e}")

    async def poll_status(self) -> None:
        """Poll thermostat status"""
        try:
            logger.debug(f"Polling: Attempting to connect to {self.mac}")
            await self.safe_connect()

            logger.debug(f"Polling: Connected to {self.mac}")
            await self.equiva_thermostat.requestStatus()
            logger.debug(f"Polling: Status requested from {self.mac}")

            mode_obj = self.equiva_thermostat.mode
            if mode_obj is None:
                raise EqivaException("Thermostat mode was not returned")

            temperature_obj = self.equiva_thermostat.temperature
            if temperature_obj is None or temperature_obj.valueC is None:
                raise EqivaException("Thermostat temperature was not returned")

            mode: list[str] = mode_obj.to_dict()
            valve: int | None = self.equiva_thermostat.valve
            temp: float = temperature_obj.valueC

            target_mode_status = self.calculate_heating_cooling_state(mode)
            current_mode_status = self.calculate_heating_cooling_state(mode, valve)

            if self.target_heating_cooling_state != target_mode_status["int"] or \
                self.current_heating_cooling_state != current_mode_status["int"]:
                logger.info(
                    f"Status changed for {self.mac}: "
                    f"targetMode: {target_mode_status['str']}, "
                    f"currentMode: {current_mode_status['str']}, "
                    f"targetTemp: {temp}C"
                )

            self.target_heating_cooling_state = target_mode_status["int"]
            self.target_temperature = temp
            self.current_heating_cooling_state = current_mode_status["int"]
            self.last_updated = strftime("%Y-%m-%d %H:%M:%S", localtime())

            logger.debug(
                f"Polling: Status changed for {self.mac}: "
                f"targetMode: {target_mode_status['str']}, "
                f"currentMode: {current_mode_status['str']}, "
                f"targetTemp: {self.target_temperature}C"
                )

        except (BleakError, EqivaException, RuntimeError, OSError) as e:
            logger.error(f"Polling failed for {self.mac}: {e}")
            self.failed_connection = True
            raise
        finally:
            try:
                await self.safe_disconnect()
            except (BleakError, EqivaException, RuntimeError, OSError) as e:
                logger.error(f"Error disconnecting from {self.mac}: {e}")

    async def set_temperature(self, temp: str) -> dict[str, Any]:
        """Set thermostat target temperature"""
        mac: str = self.mac
        if not temp:
            return {"result": "error", "message": "Temperature value is required"}
        try:
            logger.info(f"Set temperature for {mac} to {temp}")
            await self.safe_connect()
            await self.equiva_thermostat.setTemperature(temperature=Temperature(valueC=float(temp)))
            self.target_temperature = float(temp)
            return {"result": "ok", "temperature": float(temp)}
        except BleakError:
            logger.error(f"Device with address {mac} was not found")
            self.failed_connection = True
            return {"result": "error", "message": f"Device with address {mac} was not found"}
        except EqivaException as ex:
            logger.error(f"EqivaException for {mac}: {str(ex)}")
            self.failed_connection = True
            return {"result": "error", "message": str(ex)}
        except ValueError as ex:
            logger.error(f"Invalid temperature value for {mac}: {str(ex)}")
            return {"result": "error", "message": "Invalid temperature value"}
        except (RuntimeError, OSError) as ex:
            logger.error(f"Unexpected error for {mac}: {str(ex)}")
            self.failed_connection = True
            return {"result": "error", "message": "Connection failed"}
        finally:
            try:
                await self.safe_disconnect()
            except (BleakError, EqivaException, RuntimeError, OSError) as e:
                logger.error(f"Error disconnecting from {mac}: {e}")

    async def set_mode(self, mode: str) -> dict[str, Any]:
        """Set thermostat heating/cooling mode"""
        mac: str = self.mac
        if not mode:
            return {"result": "error", "message": "Mode value is required"}
        try:
            await self.safe_connect()
            if mode == '0':
                await self.equiva_thermostat.setTemperatureOff()
                self.target_heating_cooling_state = 0
            elif mode in ('1', '2'):
                await self.equiva_thermostat.setModeManual()
                self.target_heating_cooling_state = 1
            elif mode == '3':
                await self.equiva_thermostat.setModeAuto()
                self.target_heating_cooling_state = 3
            else:
                return {"result": "error", "message": "Invalid mode value"}
            mode_str = 'off' if mode == '0' else 'heating' if mode == '1' else 'auto' if mode == '3' else 'unknown'
            logger.info(f"Set mode for {mac} to {mode_str}")
            return {"result": "ok", "mode": int(mode)}
        except BleakError:
            logger.error(f"Device with address {mac} was not found")
            self.failed_connection = True
            return {"result": "error", "message": f"Device with address {mac} was not found"}
        except EqivaException as ex:
            logger.error(f"EqivaException for {mac}: {str(ex)}")
            self.failed_connection = True
            return {"result": "error", "message": str(ex)}
        except (RuntimeError, OSError) as ex:
            logger.error(f"Unexpected error for {mac}: {str(ex)}")
            self.failed_connection = True
            return {"result": "error", "message": "Connection failed"}
        finally:
            try:
                await self.safe_disconnect()
            except (BleakError, EqivaException, RuntimeError, OSError) as e:
                logger.error(f"Error disconnecting from {mac}: {e}")

    def get_all_data(self) -> dict[str, Any]:
        """Get all thermostat data"""
        return {
            "mac": self.mac,
            "targetHeatingCoolingState": self.target_heating_cooling_state,
            "targetTemperature": self.target_temperature,
            "currentHeatingCoolingState": self.current_heating_cooling_state,
            "currentTemperature": self.current_temperature,
            "currentRelativeHumidity": self.current_relative_humidity,
            "last_updated": self.last_updated,
            "first_seen": self.first_seen,
            "DHT_connected": self.dht_connected,
            "failed_connection": self.failed_connection,
            "min_temperature": self.min_temperature,
            "max_temperature": self.max_temperature,
        }

    def save(self) -> dict[str, Any]:
        """Save current thermostat state to a dictionary"""
        return {
            "mac": self.mac,
            "targetHeatingCoolingState": self.target_heating_cooling_state,
            "targetTemperature": self.target_temperature,
            "currentHeatingCoolingState": self.current_heating_cooling_state,
            "currentTemperature": self.current_temperature,
            "currentRelativeHumidity": self.current_relative_humidity,
            "first_seen": self.first_seen,
            "min_temperature": self.min_temperature,
            "max_temperature": self.max_temperature,
            "last_updated": self.last_updated,
        }
