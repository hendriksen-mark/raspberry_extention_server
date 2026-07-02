"""
This module provides functionality to fetch and synchronize the state of various devices.
"""
from typing import Any
import asyncio
import threading
import logging
from bleak.exc import BleakError

from eqiva_thermostat import EqivaException
import logManager

import config_manager
from server_objects.dht_object import DHTObject
from server_objects.thermostat_object import ThermostatObject
from server_objects.fan_object import FanObject
from server_objects.klok_object import KlokObject
from server_objects.powerbutton_object import PowerButtonObject

logger: logging.Logger = logManager.logger.get_logger(__name__)
SERVER_CONFIG: dict[str, Any] = config_manager.SERVER_CONFIG.yaml_config

# Global shutdown events for immediate thread termination
_shutdown_event = threading.Event()
_thermostat_shutdown = threading.Event()
_dht_shutdown = threading.Event()
_fan_shutdown = threading.Event()
_klok_shutdown = threading.Event()
_powerbutton_shutdown = threading.Event()

# Async event/loop state for thermostat shutdown
_thermostat_async_state: dict[str, Any] = {
    "shutdown_event": asyncio.Event(),
    "shutdown_loop": None,
}

def _ensure_async_event_loop():
    """Ensure async events are properly initialized for current event loop"""
    current_loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    if _thermostat_async_state["shutdown_loop"] is not current_loop:
        _thermostat_async_state["shutdown_event"] = asyncio.Event()
        _thermostat_async_state["shutdown_loop"] = current_loop

async def sync_with_thermostats() -> None:
    """
    Synchronize the state of the thermostats with their actual state.
    """
    _ensure_async_event_loop()  # Ensure async event is valid for this loop

    while SERVER_CONFIG["config"]["thermostats"]["enabled"] and not _thermostat_shutdown.is_set():
        logger.debug("start thermostats sync")
        interval: int = SERVER_CONFIG["config"]["thermostats"]["interval"]

        for thermostat in SERVER_CONFIG["thermostats"].values():
            if _thermostat_shutdown.is_set():
                break
            thermostat: ThermostatObject = thermostat
            try:
                logger.debug("fetch " + thermostat.mac)
                await thermostat.poll_status()
                thermostat.failed_connection = False
            except BleakError as e:
                logger.error(f"Polling: BLE error for {thermostat.mac}: {e}")
                thermostat.failed_connection = True
            except EqivaException as e:
                logger.error(f"Polling: EqivaException for {thermostat.mac}: {e}")
                thermostat.failed_connection = True
            finally:
                try:
                    await thermostat.safe_disconnect()
                    logger.debug(f"Polling: Disconnected from {thermostat.mac}")
                except (BleakError, EqivaException, RuntimeError) as e:
                    logger.error(f"Polling: Error disconnecting from {thermostat.mac}: {e}")

        # Simple sleep with shutdown check - much more efficient
        sleep_time: float = max(10, interval)
        try:
            await asyncio.wait_for(
                _thermostat_async_state["shutdown_event"].wait(),
                timeout=sleep_time
            )
            # If we get here, shutdown was requested
            break
        except asyncio.TimeoutError:
            # Timeout is expected - continue the loop
            continue


def sync_with_thermostats_threaded() -> None:
    """
    Thread wrapper for the async sync_with_thermostats function
    """
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(sync_with_thermostats())
    except (RuntimeError, asyncio.CancelledError) as e:
        logger.error(f"Error in thermostat sync thread: {e}")
    finally:
        try:
            loop.close()
        except RuntimeError as e:
            logger.error(f"Error closing sync loop: {e}")

def disconnect_thermostats() -> None:
    """
    Disconnect all thermostats.
    """
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def cleanup_all():
        tasks: list[asyncio.Task[None]] = []
        for thermostat in SERVER_CONFIG["thermostats"].values():
            thermostat: ThermostatObject = thermostat
            try:
                # Create a timeout wrapper for each disconnect
                task: asyncio.Task[None] = asyncio.create_task(
                    asyncio.wait_for(thermostat.safe_disconnect(), timeout=5.0)
                )
                tasks.append(task)
            except (BleakError, EqivaException, RuntimeError) as e:
                logger.error(f"Cleanup: Error preparing disconnect for {thermostat.mac}: {e}")

        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except (RuntimeError, asyncio.CancelledError) as e:
                logger.error(f"Cleanup: Error during gather: {e}")

    try:
        logger.info("Disconnecting all thermostats...")
        loop.run_until_complete(cleanup_all())
    except (RuntimeError, asyncio.CancelledError) as e:
        logger.error(f"Cleanup: Error during cleanup: {e}")
    finally:
        try:
            loop.close()
        except RuntimeError as e:
            logger.error(f"Cleanup: Error closing loop: {e}")

    logger.info("Cleanup: All thermostats disconnected.")

def run_dht_service() -> None:
    """
    Placeholder for DHT temperature reading logic.
    This function should be implemented to read from the DHT sensor.
    """
    while SERVER_CONFIG["config"]["dht"]["enabled"] and not _dht_shutdown.is_set() and "dht" in SERVER_CONFIG:
        interval: int = SERVER_CONFIG["config"]["dht"]["interval"]
        try:
            dht: DHTObject = SERVER_CONFIG["dht"]
            if dht:
                dht.read_dht_temperature()
        except (RuntimeError, OSError, ValueError, AttributeError) as e:
            logger.error(f"Error reading DHT temperature: {e}")

        # Use event.wait() instead of sleep loops for immediate shutdown
        if _dht_shutdown.wait(timeout=max(5, interval)):
            # Event was set - shutdown requested
            break

def run_fan_service() -> None:
    """
    Placeholder for fan service logic.
    This function should be implemented to control the fan based on temperature.
    """
    while SERVER_CONFIG["config"]["fan"]["enabled"] and not _fan_shutdown.is_set() and SERVER_CONFIG.get("fan"):
        interval: int = SERVER_CONFIG["config"]["fan"]["interval"]
        try:
            for fan in list(SERVER_CONFIG["fan"].values()):
                fan: FanObject = fan
                fan.run()
        except (RuntimeError, OSError, ValueError) as e:
            logger.error(f"Error in fan service: {e}")

        # Use event.wait() instead of sleep loops for immediate shutdown
        if _fan_shutdown.wait(timeout=max(5, interval)):
            # Event was set - shutdown requested
            break

def stop_fan_service() -> None:
    """
    Stop the fan service.
    This function should be implemented to clean up fan resources.
    """
    _fan_shutdown.set()  # Signal immediate shutdown
    try:
        for fan in SERVER_CONFIG.get("fan", {}).values():
            fan: FanObject = fan
            fan.cleanup()
        logger.info("Fan service stopped successfully.")
    except (RuntimeError, OSError) as e:
        logger.error(f"Error stopping fan service: {e}")

def run_klok_service() -> None:
    """
    Placeholder for klok service logic.
    This function should be implemented to update the klok display.
    """
    while SERVER_CONFIG["config"]["klok"]["enabled"] and not _klok_shutdown.is_set() and "klok" in SERVER_CONFIG:
        try:
            klok: KlokObject = SERVER_CONFIG["klok"]
            if klok:
                klok.show()
        except (RuntimeError, OSError, AttributeError) as e:
            logger.error(f"Error in klok service: {e}")

        # Use event.wait() with shorter timeout for responsive doublepoint updates
        if _klok_shutdown.wait(timeout=0.1):
            # Event was set - shutdown requested
            break

def stop_klok_service() -> None:
    """
    Stop the klok service.
    This function should be implemented to clean up klok resources.
    """
    _klok_shutdown.set()  # Signal immediate shutdown
    try:
        klok: KlokObject = SERVER_CONFIG["klok"]
        if klok:
            klok.display.cleanup()
            logger.info("Klok service stopped successfully.")
    except (KeyError, RuntimeError, OSError, AttributeError) as e:
        logger.error(f"Error stopping klok service: {e}")

def run_powerbutton_service() -> None:
    """
    Placeholder for power button service logic.
    This function should be implemented to handle power button events.
    """
    while SERVER_CONFIG["config"]["powerbutton"]["enabled"] and not _powerbutton_shutdown.is_set() and "powerbutton" in SERVER_CONFIG:
        try:
            powerbutton: PowerButtonObject = SERVER_CONFIG["powerbutton"]
            if powerbutton:
                powerbutton.run()
        except (KeyError, RuntimeError, OSError, ValueError) as e:
            logger.error(f"Error in power button service: {e}")

        # Use event.wait() instead of sleep for immediate shutdown
        if _powerbutton_shutdown.wait(timeout=0.1):
            # Event was set - shutdown requested
            break

def stop_powerbutton_service() -> None:
    """
    Stop the power button service.
    This function should be implemented to clean up power button resources.
    """
    _powerbutton_shutdown.set()  # Signal immediate shutdown
    try:
        powerbutton: PowerButtonObject = SERVER_CONFIG["powerbutton"]
        if powerbutton:
            powerbutton.cleanup()
            logger.info("Power button service stopped successfully.")
    except (KeyError, RuntimeError, OSError) as e:
        logger.error(f"Error stopping power button service: {e}")

def stop_dht_service() -> None:
    """
    Stop the DHT temperature reading service.
    """
    _dht_shutdown.set()  # Signal immediate shutdown
    logger.info("DHT service stopped.")

def stop_thermostat_service() -> None:
    """
    Stop the thermostat synchronization service.
    """
    _thermostat_shutdown.set()  # Signal immediate shutdown
    shutdown_loop: asyncio.AbstractEventLoop | None = _thermostat_async_state["shutdown_loop"]
    if shutdown_loop and not shutdown_loop.is_closed():
        shutdown_loop.call_soon_threadsafe(_thermostat_async_state["shutdown_event"].set)
    logger.info("Thermostat service stopped.")

def stop_all_services() -> None:
    """
    Stop all services immediately by setting all shutdown events.
    """
    _shutdown_event.set()
    _thermostat_shutdown.set()
    shutdown_loop: asyncio.AbstractEventLoop | None = _thermostat_async_state["shutdown_loop"]
    if shutdown_loop and not shutdown_loop.is_closed():
        shutdown_loop.call_soon_threadsafe(_thermostat_async_state["shutdown_event"].set)
    _dht_shutdown.set()
    _fan_shutdown.set()
    _klok_shutdown.set()
    _powerbutton_shutdown.set()
    logger.info("All stateFetch services shutdown events set.")
