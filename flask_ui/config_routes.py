"""Flask-RESTful routes for server configuration management."""
import logging
from typing import Any

from flask import request
from flask_restful import Resource
from werkzeug.security import generate_password_hash

import logManager

import config_manager
from services.update_manager import github_check, github_install

logger: logging.Logger = logManager.logger.get_logger(__name__)

SERVER_CONFIG: dict[str, Any] = config_manager.SERVER_CONFIG.yaml_config

class ConfigRoute(Resource):
    """
    Flask-RESTful resource for managing server configuration.
    """
    def get(self, _resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Handle GET requests for configuration resources
        URL: /config/ or /config/resource
        """
        return SERVER_CONFIG["config"], 200

    def put(self, resource: str | None = None) -> tuple[dict[str, Any], int]:
        """
        Update configuration for a specific resource
        """
        try:
            put_dict: dict[str, Any] = request.get_json(force=True)
            logger.debug(f"PUT request for resource: {resource}, data: {put_dict}")
            if not put_dict:
                return {"error": "No data provided"}, 400

            changes_made: list[str] = []

            # Handle software updates
            if "swupdate2" in put_dict:
                swupdate: dict[str, Any] = put_dict["swupdate2"]
                if swupdate.get("checkforupdate"):
                    github_check()
                    changes_made.append("checked for updates")
                if swupdate.get("install"):
                    github_install()
                    changes_made.append("installed updates")

            # Handle user password updates
            if "users" in put_dict:
                self._update_user_passwords(put_dict["users"])
                changes_made.append("updated user passwords")

            # Handle log level changes
            if "system" in put_dict:
                if "loglevel" in put_dict["system"]:
                    log_changes = logManager.logger.configure_logger(put_dict["system"]["loglevel"])
                    logger.info(f"Log level changed to {put_dict['system']['loglevel']}:")
                    if log_changes == "No changes made to logger levels":
                        logger.warning("No changes made to log level")
                    else:
                        logger.debug("Log level changes:")
                        for change in log_changes:
                            logger.debug(f"  - {change}")
                    changes_made.append(f"changed log level to {put_dict['system']['loglevel']}")

                if "branch" in put_dict["system"]:
                    changes_made.append(f"changed branch to {put_dict['system']['branch']}")

            # Handle service configuration updates
            service_configs: list[str] = [
                "thermostats", "dht", "klok", "fan",
                "powerbutton", "webserver", "system", "swupdate2"
                ]
            for service in service_configs:
                if service in put_dict:
                    service_changes: list[str] = self._update_service_config(service, put_dict[service])
                    if service_changes:
                        changes_made.extend([f"{service}: {change}" for change in service_changes])

            # Save configuration if changes were made
            if changes_made:
                try:
                    config_manager.SERVER_CONFIG.save_config(backup=False, resource="config")
                    logger.info(f"Configuration updated - Changes: {', '.join(changes_made)}")
                    return {
                        "message": "Configuration updated successfully",
                        "changes": changes_made,
                        "config": SERVER_CONFIG["config"]
                    }, 200
                except (OSError, KeyError, ValueError) as e:
                    logger.error(f"Failed to save configuration: {e}")
                    return {"error": "Failed to save configuration"}, 500
            else:
                return {"message": "No changes made", "config": SERVER_CONFIG["config"]}, 200

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error processing PUT request: {e}")
            return {"error": "Failed to process request"}, 500

    def _update_user_passwords(self, users_data: dict[str, Any]) -> None:
        """Update user passwords"""
        for key, value in users_data.items():
            for email, user_info in SERVER_CONFIG["config"]["users"].items():
                if users_data[key] == user_info:
                    if "password" in value:
                        password_hash: str = generate_password_hash(str(value['password']))
                        SERVER_CONFIG["config"]["users"][email]["password"] = password_hash

    def _update_service_config(self, service: str, service_data: dict[str, Any]) -> list[str]:
        """Update service configuration and return list of changes made"""
        changes: list[str] = []

        # Ensure the service config exists
        if service not in SERVER_CONFIG["config"]:
            SERVER_CONFIG["config"][service] = {}

        # Update enabled status
        if "enabled" in service_data:
            old_enabled: bool | None = SERVER_CONFIG["config"][service].get("enabled")
            new_enabled: bool | None = service_data["enabled"]
            if old_enabled != new_enabled:
                SERVER_CONFIG["config"][service]["enabled"] = new_enabled
                changes.append(f"enabled: {old_enabled} -> {new_enabled}")

        # Update interval (if applicable)
        if "interval" in service_data and service in ["thermostats", "dht", "fan", "webserver"]:
            old_interval: float | None = SERVER_CONFIG["config"][service].get("interval")
            new_interval: float | None = service_data["interval"]
            if old_interval != new_interval:
                # Validate interval is a positive number
                try:
                    if new_interval is None:
                        raise TypeError("interval cannot be None")
                    interval_val: float = float(new_interval)
                    if interval_val > 0:
                        SERVER_CONFIG["config"][service]["interval"] = new_interval
                        changes.append(f"interval: {old_interval} -> {new_interval}")
                    else:
                        logger.warning(f"Invalid interval value for {service}: {new_interval}")
                except (ValueError, TypeError):
                    logger.warning(f"Invalid interval value for {service}: {new_interval}")

        # Update other service-specific configurations
        for key, value in service_data.items():
            if key not in ["enabled", "interval"]:
                old_value: Any = SERVER_CONFIG["config"][service].get(key)
                if old_value != value:
                    SERVER_CONFIG["config"][service][key] = value
                    changes.append(f"{key}: {old_value} -> {value}")

        return changes
