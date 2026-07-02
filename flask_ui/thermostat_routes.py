"""
HomeKit/Homebridge compatible routes
"""
import logging
from typing import Any

from flask import request
from flask_restful import Resource
from bleak.exc import BleakError

import logManager
from eqiva_thermostat import EqivaException

import config_manager

from services.utils import validate_mac_address, format_mac, next_free_id, async_route
from server_objects.thermostat_object import ThermostatObject

logger: logging.Logger = logManager.logger.get_logger(__name__)

SERVER_CONFIG: dict[str, Any] = config_manager.SERVER_CONFIG.yaml_config

def find_thermostat(mac: str) -> ThermostatObject | None:
    """
    Find thermostat by MAC address
    """
    for thermostat in SERVER_CONFIG["thermostats"].values():
        if thermostat.mac.lower() == mac.lower():
            return thermostat
    return None

def create_thermostat(mac: str, post_dict: dict[str, Any] | None = None) -> ThermostatObject:
    """
    Create a new thermostat object if it doesn't exist
    """
    if find_thermostat(mac) is not None:
        raise ValueError(f"Thermostat with MAC {mac} already exists")

    data: dict[str, Any] = {"mac": mac}
    data["id"] = next_free_id(SERVER_CONFIG, "thermostats")
    if post_dict:
        data.update(post_dict)
    return ThermostatObject(data)

class ThermostatRoute(Resource):
    """
    Flask-RESTful resource for managing thermostat configuration and control.
    """
    @async_route
    async def get(self, mac: str, resource: str | None = None, value: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle GET requests for thermostat resources
        URL: /MAC_ADDRESS/ or /MAC_ADDRESS/resource
        """
        if not validate_mac_address(mac):
            return {"error": "Invalid MAC address format"}, 400

        mac = format_mac(mac)

        thermostat: ThermostatObject | None = find_thermostat(mac)
        if not thermostat:
            logger.info(f"Thermostat with MAC {mac} not found, creating a new one")
            try:
                thermostat = create_thermostat(mac)
                SERVER_CONFIG["thermostats"][thermostat.id] = thermostat
                logger.info(f"Created new thermostat with MAC {mac}: {thermostat.save()}")
                config_manager.SERVER_CONFIG.save_config(backup=False, resource="thermostats")
            except ValueError as e:
                logger.error(f"Failed to create thermostat: {e}")
                return {"error": str(e)}, 400
            except (OSError, KeyError) as e:
                logger.error(f"Failed to save configuration: {e}")
                return {"error": "Failed to save configuration"}, 500

        # If no resource specified, return available endpoints for this thermostat
        if resource is None:
            return {
                "mac": mac,
                "available_endpoints": [
                    "status",
                    "poll",
                    "targetTemperature", 
                    "targetHeatingCoolingState"
                ],
                "description": f"Thermostat {mac} control endpoints"
            }, 200

        if resource == 'status':
            return thermostat.get_status(), 200

        if resource == 'poll':
            try:
                await thermostat.poll_status()
                return thermostat.get_status(), 200
            except BleakError:
                logger.error(f"Device with address {mac} was not found")
                return {"error": f"Device with address {mac} was not found"}, 404
            except (EqivaException, RuntimeError, OSError) as e:
                logger.error(f"Poll failed for {mac}: {e}")
                return {"error": f"Poll failed: {e}"}, 500


        elif resource == 'targetTemperature':
            if value is None:
                temp_value: str | None = request.args.get('value')
            else:
                temp_value = value
            if not temp_value:
                return {"error": "Temperature value is required as 'value' parameter"}, 400

            try:
                temperature: float = float(temp_value)
                min_temp: float = getattr(thermostat, 'min_temperature', 5.0)
                max_temp: float = getattr(thermostat, 'max_temperature', 35.0)
                if not min_temp <= temperature <= max_temp:
                    return {
                        "error": f"Temperature must be between {min_temp}°C and {max_temp}°C"
                    }, 400
            except ValueError:
                return {"error": "Invalid temperature value"}, 400
            try:
                result: dict[str, Any] = await thermostat.set_temperature(str(temperature))
                logger.info(f"HomeKit: Set targetTemperature for {mac} to {temperature}: {result}")

                if result["result"] == "ok":
                    return {"success": True, "temperature": temperature}, 200
                return result, 400

            except BleakError:
                logger.error(f"Device with address {mac} was not found")
                return {"error": f"Device with address {mac} was not found"}, 404

        elif resource == 'targetHeatingCoolingState':
            if value is None:
                mode_value: str | None = request.args.get('value')
            else:
                mode_value = value
            if not mode_value:
                return {"error": "Mode value is required as 'value' parameter"}, 400

            if mode_value not in ['0', '1', '2', '3']:
                return {"error": "Mode must be 0 (off), 1 (heat), 2 (cool), or 3 (auto)"}, 400

            try:
                result: dict[str, Any] = await thermostat.set_mode(mode_value)
                logger.info(f"HomeKit: Set targetHeatingCoolingState for {mac} to {mode_value}: {result}")

                if result["result"] == "ok":
                    return {"success": True, "mode": int(mode_value)}, 200
                return result, 400

            except BleakError:
                logger.error(f"Device with address {mac} was not found")
                return {"error": f"Device with address {mac} was not found"}, 404
        else:
            return {"error": "Resource not found"}, 404

    @async_route
    async def post(self, mac: str, _resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle POST requests for thermostat resources
        URL: /MAC_ADDRESS/resource
        """
        if not validate_mac_address(mac):
            return {"error": "Invalid MAC address format"}, 400

        mac = format_mac(mac)

        thermostat: ThermostatObject | None = find_thermostat(mac)

        post_dict: dict[str, Any] = request.get_json(force=True) if request.get_data(as_text=True) != "" else {}
        logger.info(f"POST data received: {post_dict}")

        # Validate required data for creating thermostat
        if not thermostat and not post_dict:
            return {"error": "JSON data required for creating new thermostat"}, 400

        if thermostat:
            logger.info(f"Thermostat with MAC {mac} already exists, updating it")
            # Only allow updating certain safe attributes
            allowed_attributes: set[str] = {
                'targetHeatingCoolingState',
                'targetTemperature',
                'min_temperature',
                'max_temperature'
            }
            for key, value in post_dict.items():
                if key in allowed_attributes and hasattr(thermostat, key):
                    setattr(thermostat, key, value)
                elif key not in allowed_attributes:
                    logger.warning(f"Attempted to set non-allowed attribute: {key}")
        else:
            logger.info(f"Thermostat with MAC {mac} not found, creating a new one")
            try:
                thermostat = create_thermostat(mac, post_dict)
                SERVER_CONFIG["thermostats"][thermostat.id] = thermostat
            except ValueError as e:
                logger.error(f"Failed to create thermostat: {e}")
                return {"error": str(e)}, 400

        if not thermostat:
            return {"error": f"Thermostat with MAC {mac} not found"}, 404

        try:
            logger.info(f"Updated thermostat with MAC {mac}: {thermostat.save()}")
            config_manager.SERVER_CONFIG.save_config(backup=False, resource="thermostats")
            return thermostat.save(), 200
        except (OSError, KeyError, ValueError) as e:
            logger.error(f"Failed to save configuration: {e}")
            return {"error": "Failed to save configuration"}, 500

    @async_route
    async def delete(self, mac: str, _resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle DELETE requests for thermostat resources
        URL: /MAC_ADDRESS/resource
        """
        if not validate_mac_address(mac):
            return {"error": "Invalid MAC address format"}, 400

        mac = format_mac(mac)

        thermostat: ThermostatObject | None = find_thermostat(mac)

        if thermostat:
            try:
                logger.info(f"Deleting thermostat with MAC {mac}")
                del SERVER_CONFIG["thermostats"][thermostat.id]
                config_manager.SERVER_CONFIG.save_config(backup=False, resource="thermostats")
                return {"success": True}, 200
            except (KeyError, OSError) as e:
                logger.error(f"Failed to delete thermostat: {e}")
                return {"error": "Failed to delete thermostat"}, 500
        else:
            return {"error": f"Thermostat with MAC {mac} not found"}, 404
