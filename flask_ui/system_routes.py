"""
System and configuration routes
"""
from typing import Any
import os
import logging
from flask_restful import Resource

import logManager
from server_objects.thermostat_object import ThermostatObject
from server_objects.fan_object import FanObject
from server_objects.klok_object import KlokObject
from server_objects.powerbutton_object import PowerButtonObject
from server_objects.dht_object import DHTObject
import config_manager
from services.utils import get_pi_temp

logger: logging.Logger = logManager.logger.get_logger(__name__)

SERVER_CONFIG: dict[str, Any] = config_manager.SERVER_CONFIG.yaml_config

class SystemRoute(Resource):
    """
    Flask-RESTful resource for managing system information and configuration.
    """
    def get(self, resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle GET requests for system resources
        URL: /system/ or /system/resource
        """
        response: tuple[dict[str, Any], int]
        if resource == 'pi_temp':
            try:
                temp: float = get_pi_temp()
                response = {"temperature": temp}, 200
            except RuntimeError as e:
                logger.error(f"Error reading Pi temperature: {e}")
                response = {"error": "Could not read Pi temperature"}, 503

        elif resource == "all":
            try:
                response_data, status_code = _get_all_config()
                uname = os.uname()
                response_data["pi_temp"] = get_pi_temp() if uname.sysname == "Linux" else "Unsupported OS"

                response_data["info"] = {
                        "sysname": uname.sysname,
                        "machine": uname.machine,
                        "os_version": uname.version,
                        "os_release": uname.release,
                        "server": config_manager.SERVER_CONFIG.serverCreateTime,
                        "webui": config_manager.SERVER_CONFIG.WebUICreateTime
                    }
                response = response_data, status_code
            except (OSError, KeyError, AttributeError, RuntimeError) as e:
                logger.error(f"Error getting all system info: {e}")
                response = {"error": "Failed to retrieve system information"}, 500

        elif resource == "health":
            response = health_check()

        elif resource == "config":
            response = _get_all_config()
        else:
            response = {"error": "Resource not found"}, 404
        return response

def health_check() -> tuple[dict[str, Any], int]:
    """Health check endpoint"""
    dht_obj: DHTObject | None = SERVER_CONFIG.get("dht")

    # Handle both dict and object cases for DHT
    if hasattr(dht_obj, 'get_data'):
        logger.info("DHT object found, retrieving data")
        temp, humidity = dht_obj.get_data() if dht_obj and hasattr(dht_obj, 'get_data') else (None, None)
        dht_pin: int | None = dht_obj.get_pin() if dht_obj and hasattr(dht_obj, 'get_pin') else None
    else:
        # Fallback if object not properly initialized
        logger.info("DHT object not properly initialized")
        temp: float | None = None
        humidity: float | None = None
        dht_pin: int | None = None

    return {
        "status": "healthy",
        "version": "1.0.0",
        "thermostats_connected": len(SERVER_CONFIG.get("thermostats", {})),
        "dht_sensor_active": dht_pin is not None,
        "temperature_available": temp is not None,
        "humidity_available": humidity is not None
    }, 200

def _get_all_config() -> tuple[dict[str, Any], int]:
    """Return the server configuration"""
    try:

        response: dict[str, Any] = {
            "config": SERVER_CONFIG["config"],
            "thermostats": _get_thermostat_config(),
            "fan": _get_fan_config(),
            "dht": _get_dht_config(),
            "klok": _get_klok_config(),
            "powerbutton": _get_powerbutton_config()
        }

        return response, 200
    except (KeyError, OSError, AttributeError) as e:
        logger.error(f"Error getting config: {e}")
        return {"error": "Failed to retrieve configuration"}, 500

def _get_thermostat_config() -> dict[str, Any] | str:
    """Return the thermostat configuration"""
    try:
        thermostats = SERVER_CONFIG.get("thermostats", {})
        thermostats_data = {}
        if len(thermostats) > 0:
            for key, obj in thermostats.items():
                if isinstance(obj, ThermostatObject):
                    thermostats_data.update({key: obj.save()})
        else:
            thermostats_data = "No Thermostats Configured"
        return thermostats_data
    except (KeyError, AttributeError) as e:
        logger.error(f"Error getting thermostat config: {e}")
        return "Error getting Thermostats config"

def _get_fan_config() -> dict[str, Any] | str:
    """Return the fan configuration"""
    try:
        fans = SERVER_CONFIG.get("fan", {})
        fans_data = {}
        if len(fans) > 0:
            for fid, f in fans.items():
                if isinstance(f, FanObject):
                    fans_data.update({fid: f.save()})
        else:
            fans_data = "No Fans Configured"
        return fans_data
    except (KeyError, AttributeError) as e:
        logger.error(f"Error getting fan config: {e}")
        return "Error getting Fan config"

def _get_dht_config() -> dict[str, Any] | str:
    """Return the DHT sensor configuration"""
    try:
        dht_obj: DHTObject | None = SERVER_CONFIG.get("dht")
        if dht_obj and isinstance(dht_obj, DHTObject):
            return dht_obj.save()
        return "No DHT Sensor Configured"
    except (KeyError, AttributeError) as e:
        logger.error(f"Error getting DHT config: {e}")
        return "Error getting DHT config"

def _get_klok_config() -> dict[str, Any] | str:
    """Return the Klok configuration"""
    try:
        klok_obj: KlokObject | None = SERVER_CONFIG.get("klok")
        if klok_obj and isinstance(klok_obj, KlokObject):
            return klok_obj.save()
        return "No Klok Configured"
    except (KeyError, AttributeError) as e:
        logger.error(f"Error getting Klok config: {e}")
        return "Error getting Klok config"

def _get_powerbutton_config() -> dict[str, Any] | str:
    """Return the PowerButton configuration"""
    try:
        powerbutton_obj: PowerButtonObject | None = SERVER_CONFIG.get("powerbutton")
        if powerbutton_obj and isinstance(powerbutton_obj, PowerButtonObject):
            return powerbutton_obj.save()
        return "No PowerButton Configured"
    except (KeyError, AttributeError) as e:
        logger.error(f"Error getting PowerButton config: {e}")
        return "Error getting PowerButton config"
