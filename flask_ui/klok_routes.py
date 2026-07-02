"""Flask-RESTful routes for klok (TM1637 clock display) management."""
import logging
from typing import Any

from flask import request
from flask_restful import Resource

import logManager

import config_manager
from server_objects.klok_object import KlokObject

logger: logging.Logger = logManager.logger.get_logger(__name__)

SERVER_CONFIG: dict[str, Any] = config_manager.SERVER_CONFIG.yaml_config

def find_klok() -> KlokObject | None:
    """
    Find klok service in server configuration
    """
    klok = SERVER_CONFIG.get("klok")
    return klok if isinstance(klok, KlokObject) else None

def create_klok(post_dict: dict[str, Any] | None = None) -> KlokObject:
    """
    Create a new klok object
    """
    if not post_dict:
        post_dict = {}
        logger.warning("No POST data provided, creating default klok object")
    return KlokObject(post_dict)

class KlokRoute(Resource):
    """
    Flask-RESTful resource for managing klok (TM1637 clock display) configuration and control.
    """
    def get(self, resource: str | None = None, value: str | None = None) -> tuple[dict[str, Any] | str, int]:
        """
        Handle GET requests for klok resources
        URL patterns:
        - /klok/
        - /klok/on
        - /klok/off  
        - /klok/status
        - /klok/Bri/<value>
        - /klok/infoBri
        """
        # If no resource specified, return available endpoints
        if resource is None:
            return {
                "available_endpoints": [
                    "on",
                    "off",
                    "status",
                    "Bri/<value>",
                    "infoBri"
                ],
                "description": "Klok (clock) control endpoints"
            }, 200

        # Validate request type
        valid_resources: list[str] = ["on", "off", "status", "Bri", "infoBri"]
        if resource not in valid_resources:
            return {"error": "Invalid request type. Valid types are: " + ", ".join(valid_resources)}, 400

        # Get value from URL parameter or query string
        value_param: str | None = value if value is not None else request.args.get("value")

        logger.info(f"Klok GET request: resource={resource}, value={value_param}")

        # Get the klok service (assuming it's a single service like DHT)
        klok: KlokObject | None = find_klok()

        if klok is None:
            logger.error("Klok service not found in server configuration")
            return {"error": "Klok service not found in server configuration"}, 404

        if resource == "on":
            klok.set_power(True)
            return {"status": "on"}, 200

        if resource == "off":
            klok.set_power(False)
            return {"status": "off"}, 200

        if resource == "status":
            state: int = 1 if klok.power_state else 0
            return str(state), 200

        if resource == "Bri":
            if value_param is not None:
                try:
                    brightness_value: int = int(value_param)
                    klok.set_brightness(brightness_value)
                    return {"status": "done"}, 200
                except ValueError:
                    return {"error": "Invalid brightness value"}, 400
            else:
                return {"error": "Brightness value is required"}, 400

        if resource == "infoBri":
            bri_percent: int = klok.get_brightness_percent()
            return str(bri_percent), 200

        return klok.get_all_data(), 200

    def post(self, _resource: str | None = None, _value: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle POST requests for klok resources
        URL: /klok
        """
        post_dict: dict[str, Any] = request.get_json(force=True) if request.get_data(as_text=True) != "" else {}
        logger.info(f"POST data received: {post_dict}")

        klok: KlokObject | None = find_klok()

        if klok:
            logger.info("Klok already exists, updating configuration")
            # Only allow updating certain safe attributes
            allowed_attributes: set[str] = {
                'CLK_pin',
                'DIO_pin',
                'brightness',
                'power_state',
                'doublepoint'
            }
            for key, item_value in post_dict.items():
                if key in allowed_attributes and hasattr(klok, key):
                    setattr(klok, key, item_value)
                elif key not in allowed_attributes:
                    logger.warning(f"Attempted to set non-allowed attribute: {key}")
        else:
            logger.info("Klok not found, creating a new one")
            try:
                klok = create_klok(post_dict)
                SERVER_CONFIG["klok"] = klok
            except ValueError as e:
                logger.error(f"Failed to create klok: {e}")
                return {"error": str(e)}, 400

        if not klok:
            return {"error": "Klok not found or failed to create klok"}, 500

        try:
            logger.info(f"Updated klok configuration: {klok.save()}")
            config_manager.SERVER_CONFIG.save_config(backup=False, resource="klok")
            return klok.save(), 200
        except (OSError, KeyError, ValueError) as e:
            logger.error(f"Failed to save configuration: {e}")
            return {"error": "Failed to save configuration"}, 500

    def delete(self, _resource: str | None = None, _value: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle DELETE requests for klok resources
        URL: /klok
        """
        klok: KlokObject | None = find_klok()
        if klok:
            try:
                logger.info("Deleting klok service")
                del SERVER_CONFIG["klok"]
                config_manager.SERVER_CONFIG.save_config(backup=False, resource="klok")
                return {"success": True}, 200
            except (KeyError, OSError) as e:
                logger.error(f"Failed to delete klok service: {e}")
                return {"error": "Failed to delete klok service"}, 500
        else:
            logger.error("Klok service not found in server configuration")
            return {"error": "Klok service not found in server configuration"}, 404
