"""
DHT sensor related routes
"""
import logging
from typing import Any

from flask import request
from flask_restful import Resource

import logManager

import config_manager
from server_objects.dht_object import DHTObject

logger: logging.Logger = logManager.logger.get_logger(__name__)

SERVER_CONFIG: dict[str, Any] = config_manager.SERVER_CONFIG.yaml_config

def find_dht() -> DHTObject | None:
    """
    Find DHT service in server configuration
    """
    dht = SERVER_CONFIG.get("dht")
    return dht if isinstance(dht, DHTObject) else None

def create_dht(post_dict: dict[str, Any] | None = None) -> DHTObject:
    """
    Create a new DHT object if it doesn't exist
    """
    if not post_dict:
        post_dict = {}
        logger.warning("No POST data provided, creating default DHT object")
    return DHTObject(post_dict)

def get_default_sensor_data(warning_message: str) -> tuple[dict[str, Any], int]:
    """
    Return default sensor data with a warning message
    """
    return {
        "temperature": 22.0,  # Default temperature
        "humidity": 50.0,     # Default humidity
        "warning": warning_message
    }, 200

class DHTRoute(Resource):
    """
    Flask-RESTful resource for managing DHT sensor data and configuration.
    """
    def get(self, resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
            Handle GET requests for DHT sensor data
        """
        logger.info(f"DHT GET request: resource: {resource}")
        dht: DHTObject | None = find_dht()

        if dht is None:
            logger.error("DHT service not found in server configuration, returning default values")
            return get_default_sensor_data("DHT sensor not configured")

        if resource == "info":
            # Return DHT configuration info
            try:
                dht_info: dict[str, Any] = dht.get_all_data()
                logger.info(f"Returning DHT info: {dht_info}")
                return dht_info, 200
            except KeyError as e:
                logger.error(f"KeyError: {e}")
                return {"error": "DHT sensor configuration not found"}, 404
            except (AttributeError, RuntimeError) as e:
                logger.error(f"Failed to retrieve DHT info: {e}")
                return {"error": "Failed to retrieve DHT info"}, 500

        else:
            pin: int | None = dht.get_pin()
            # If no pin is set at all, return default values
            if pin is None:
                logger.warning("DHT_PIN is not set, returning default values.")
                return get_default_sensor_data("DHT sensor not configured")

            # Get current sensor values
            temp, hum = dht.get_data()

            if temp is None or hum is None:
                logger.warning("DHT sensor data not available, returning default values")
                return get_default_sensor_data("DHT sensor data not available")

            logger.info("Returning DHT data")
            logger.debug(f"Temperature: {temp}°C, Humidity: {hum}%, Pin: {pin}")

            return {
                "temperature": temp,
                "humidity": hum,
                "pin": pin
            }, 200

    def post(self, _resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Update DHT sensor configuration
        """
        post_dict: dict[str, Any] = request.get_json(force=True) if request.get_data(as_text=True) != "" else {}
        logger.info(f"POST data received: {post_dict}")

        dht: DHTObject | None = find_dht()

        if dht:
            logger.info("DHT already exists, updating configuration")
            allowed_attributes: set[str] = {
                'dht_pin',
                'sensor_type',
                'MIN_DHT_TEMP',
                'MAX_DHT_TEMP',
                'MIN_HUMIDITY',
                'MAX_HUMIDITY',
                'DHT_TEMP_CHANGE_THRESHOLD',
                'DHT_HUMIDITY_CHANGE_THRESHOLD'
                }
            for key, value in post_dict.items():
                if key in allowed_attributes and hasattr(dht, key):
                    setattr(dht, key, value)
                elif key not in allowed_attributes:
                    logger.warning(f"Attempted to set non-allowed attribute: {key}")
        else:
            logger.info("DHT not found, creating a new one")
            try:
                dht = create_dht(post_dict)
                SERVER_CONFIG["dht"] = dht
            except ValueError as e:
                logger.error(f"Failed to create DHT: {e}")
                return {"error": str(e)}, 400

        if not dht:
            return {"error": "DHT not found or failed to create DHT"}, 500

        try:
            logger.info(f"Updated DHT configuration: {dht.save()}")
            config_manager.SERVER_CONFIG.save_config(backup=False, resource="dht")
            return dht.save(), 200
        except (OSError, KeyError, ValueError) as e:
            logger.error(f"Failed to save configuration: {e}")
            return {"error": "Failed to save configuration"}, 500

    def delete(self, _resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Delete DHT sensor configuration
        """
        dht: DHTObject | None = find_dht()
        if dht:
            try:
                logger.info("Deleting DHT configuration")
                del SERVER_CONFIG["dht"]
                config_manager.SERVER_CONFIG.save_config(backup=False, resource="dht")
                return {"success": True}, 200
            except (KeyError, OSError) as e:
                logger.error(f"Failed to delete DHT configuration: {e}")
                return {"error": "Failed to delete DHT configuration"}, 500
        else:
            logger.error("DHT service not found in server configuration")
            return {"error": "DHT service not found in server configuration"}, 404
