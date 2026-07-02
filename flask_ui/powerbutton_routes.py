"""Flask-RESTful routes for power button management."""
import logging
from typing import Any

from flask import request
from flask_restful import Resource

import logManager

import config_manager
from server_objects.powerbutton_object import PowerButtonObject

logger: logging.Logger = logManager.logger.get_logger(__name__)

SERVER_CONFIG: dict[str, Any] = config_manager.SERVER_CONFIG.yaml_config

def find_powerbutton() -> PowerButtonObject | None:
    """
    Find powerbutton service in server configuration
    """
    powerbutton = SERVER_CONFIG.get("powerbutton")
    return powerbutton if isinstance(powerbutton, PowerButtonObject) else None

def create_powerbutton(post_dict: dict[str, Any] | None = None) -> PowerButtonObject:
    """
    Create a new powerbutton object if it doesn't exist
    """
    if not post_dict:
        post_dict = {}
        logger.warning("No POST data provided, creating default powerbutton object")
    return PowerButtonObject(post_dict)

class PowerButtonRoute(Resource):
    """
    Flask-RESTful resource for managing power button configuration and control.
    """
    def get(self, _resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle GET requests for powerbutton resources
        """
        powerbutton: PowerButtonObject | None = find_powerbutton()

        if powerbutton is None:
            return {"error": "PowerButton service not found in server configuration"}, 404

        return powerbutton.get_all_data(), 200

    def post(self, _resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle POST requests for powerbutton resources
        """
        post_dict: dict[str, Any] = request.get_json(force=True) if request.get_data(as_text=True) != "" else {}
        logger.info(f"POST data received: {post_dict}")

        power_button: PowerButtonObject | None = find_powerbutton()

        if power_button:
            logger.info("PowerButton already exists, updating it")
            # Only allow updating certain safe attributes
            allowed_attributes: set[str] = {
                'button_pin',
                'long_press_duration',
                'debounce_time',
                'led_pin',
                'led_brightness',
                'led_dma',
                'host_shutdown_url',
                'host_api_key',
            }
            for key, value in post_dict.items():
                if key in allowed_attributes and hasattr(power_button, key):
                    setattr(power_button, key, value)
                elif key not in allowed_attributes:
                    logger.warning(f"Attempted to set non-allowed attribute: {key}")
        else:
            logger.info("PowerButton not found, creating a new one")
            try:
                power_button = create_powerbutton(post_dict)
                SERVER_CONFIG["powerbutton"] = power_button
            except ValueError as e:
                logger.error(f"Failed to create powerbutton: {e}")
                return {"error": str(e)}, 400

        if not power_button:
            return {"error": "PowerButton not found or failed to create PowerButton"}, 500

        try:
            logger.info(f"Updated PowerButton configuration: {power_button.save()}")
            config_manager.SERVER_CONFIG.save_config(backup=False, resource="powerbutton")
            return power_button.save(), 200
        except (OSError, KeyError, ValueError) as e:
            logger.error(f"Failed to save configuration: {e}")
            return {"error": "Failed to save configuration"}, 500

    def delete(self, _resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle DELETE requests for powerbutton resources
        """
        power_button: PowerButtonObject | None = find_powerbutton()
        if power_button:
            try:
                logger.info("Deleting PowerButton service")
                del SERVER_CONFIG["powerbutton"]
                config_manager.SERVER_CONFIG.save_config(backup=False, resource="powerbutton")
                return {"success": True}, 200
            except (KeyError, OSError) as e:
                logger.error(f"Failed to delete PowerButton service: {e}")
                return {"error": "Failed to delete PowerButton service"}, 500
        else:
            logger.error("PowerButton service not found in server configuration")
            return {"error": "PowerButton service not found in server configuration"}, 404
