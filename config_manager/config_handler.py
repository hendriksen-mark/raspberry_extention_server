"""
This module provides the Config class for managing the configuration.
"""
from pathlib import Path
from typing import Any, Optional, cast
import sys
import os
import signal
from copy import deepcopy
from datetime import datetime, timezone
import subprocess
import shutil
import zipfile
import tempfile
import logging
import yaml
from werkzeug.security import generate_password_hash

import logManager

from server_objects.thermostat_object import ThermostatObject
from server_objects.dht_object import DHTObject
from server_objects.klok_object import KlokObject
from server_objects.fan_object import FanObject
from server_objects.powerbutton_object import PowerButtonObject
from .argument_handler import parse_arguments

logger: logging.Logger = logManager.logger.get_logger(__name__)

class NoAliasDumper(yaml.SafeDumper):
    """
    YAML dumper that ignores aliases to prevent the use of anchors and references in the output.
    """
    def ignore_aliases(self, data: Any) -> bool:
        return True

def _open_yaml(path: str) -> Any:
    """
    Open a YAML file and return its contents.

    Args:
        path (str): The path to the YAML file.

    Returns:
        Any: The contents of the YAML file.
    """
    with open(path, 'r', encoding="utf-8") as fp:
        return yaml.load(fp, Loader=yaml.FullLoader)

def _write_yaml(path: str, contents: Any) -> None:
    """
    Write contents to a YAML file.

    Args:
        path (str): The path to the YAML file.
        contents (Any): The contents to write to the YAML file.
    """
    with open(path, 'w', encoding="utf-8") as fp:
        yaml.dump(contents, fp, Dumper=NoAliasDumper, allow_unicode=True, sort_keys=False)

class Config:
    """
    Config class for managing the configuration.
    """
    argsDict: dict[str, Any] = parse_arguments()
    configDir: str = argsDict["CONFIG_PATH"]
    runningDir: str = argsDict["RUNNING_PATH"]
    serverCreateEpoch: float = os.stat(f"{runningDir}/api.py").st_mtime
    serverCreateTime: str = datetime.fromtimestamp(serverCreateEpoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    WebUICreateEpoch: float = os.stat("flask_ui/templates/index.html").st_mtime
    WebUICreateTime: str = datetime.fromtimestamp(WebUICreateEpoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    ip: str = argsDict["HOST_IP"]
    argDebug: bool = argsDict["DEBUG"]
    bindIp: str = argsDict["BIND_IP"]
    httpPort: int = argsDict["HTTP_PORT"]

    def __init__(self) -> None:
        """
        Initialize the Config class.
        """
        self.yaml_config: dict[str, Any] = {}
        if not os.path.exists(self.configDir):
            os.makedirs(self.configDir)

    def _set_default_config_values(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Set default configuration values.

        Args:
            config (dict[str, Any]): The configuration dictionary.

        Returns:
            dict[str, Any]: The updated configuration dictionary.
        """
        defaults: dict[str, Any] = {
            "users": {
                "admin": {
                    "password": generate_password_hash("admin")
                }
            },
            "thermostats": {
                "enabled": False,
                "interval": 300
            },
            "dht": {
                "enabled": False,
                "interval": 5
            },
            "klok": {
                "enabled": False
            },
            "fan": {
                "enabled": False,
                "interval": 5
            },
            "powerbutton": {
                "enabled": False
            },
            "webserver": {
                "interval": 2
            },
            "swupdate2": {
                "autoinstall": {
                    "on": False,
                    "updatetime": "T14:00:00"
                },
                "checkforupdate": False,
                "lastchange": "2020-12-13T10:30:15",
                "state": "noupdates",
                "install": False
            },
            "system": {
                "loglevel": "INFO",
                "branch": "main"
            },
        }
        for key, value in defaults.items():
            if key not in config:
                config[key] = value
        return config

    def _upgrade_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Upgrade the configuration if necessary.

        Args:
            config (dict[str, Any]): The configuration dictionary.

        Returns:
            dict[str, Any]: The upgraded configuration dictionary.
        """
        # Only set branch to default if it's missing (new installation)
        if "branch" not in config["system"]:
            config["system"]["branch"] = "main"

        if "loglevel" not in config["system"] or config["system"]["loglevel"] != ("DEBUG" if self.argDebug else "INFO"):
            config["system"]["loglevel"] = "DEBUG" if self.argDebug else "INFO"
        logManager.logger.configure_logger(config["system"]["loglevel"])
        logger.info(f"Debug logging {'enabled' if self.argDebug else 'disabled'}!")
        return config

    def _load_yaml_file(self, filename: str, default: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        """
        Load a YAML file and return its contents.

        Args:
            filename (str): The name of the YAML file.
            default (Optional[dict[str, Any]]): The default value if the file does not exist.

        Returns:
            Optional[dict[str, Any]]: The contents of the YAML file or the default value.
        """
        path: str = os.path.join(self.configDir, filename)
        if os.path.exists(path):
            return _open_yaml(path)
        return default

    def _load_thermostats(self) -> None:
        """
        Load thermostats from the YAML configuration.
        """
        thermostats: dict[str, Any] = cast(dict[str, Any], self._load_yaml_file("thermostats.yaml", {}))
        for thermostat, data in thermostats.items():
            data["id"] = thermostat
            self.yaml_config["thermostats"][thermostat] = ThermostatObject(data)

    def _load_dht(self) -> None:
        """
        Load DHT sensor configuration from the YAML file.
        """
        dht_data: dict[str, Any] = cast(dict[str, Any], self._load_yaml_file("dht.yaml", {}))
        if dht_data != {}:
            self.yaml_config["dht"] = DHTObject(dht_data)

    def _load_klok(self) -> None:
        """
        Load klok configuration from the YAML file.
        """
        klok_data: dict[str, Any] = cast(dict[str, Any], self._load_yaml_file("klok.yaml", {}))
        if klok_data != {}:
            self.yaml_config["klok"] = KlokObject(klok_data)

    def _load_fan(self) -> None:
        """
        Load fan configuration from the YAML file.
        """
        fan_data: dict[str, Any] = cast(dict[str, Any], self._load_yaml_file("fan.yaml", {}))
        # Migrate old single-fan format (flat keys, no nested dicts)
        if fan_data and not any(isinstance(v, dict) for v in fan_data.values()):
            fan_data = {"1": {**fan_data, "name": "Fan 1"}}
        for fan_id, data in fan_data.items():
            data["id"] = fan_id
            self.yaml_config["fan"][fan_id] = FanObject(data)

    def _load_powerbutton(self) -> None:
        """
        Load power button configuration from the YAML file.
        """
        powerbutton_data: dict[str, Any] = cast(dict[str, Any], self._load_yaml_file("powerbutton.yaml", {}))
        if powerbutton_data != {}:
            self.yaml_config["powerbutton"] = PowerButtonObject(powerbutton_data)

    def _setup_dht_callbacks(self) -> None:
        """
        Set up DHT sensor callbacks to update thermostats when temperature/humidity changes.
        This method should be called after both DHT and thermostat objects are loaded.
        """
        dht_obj = self.yaml_config.get("dht")
        dht_obj: Optional[DHTObject] = dht_obj if isinstance(dht_obj, DHTObject) else None
        if dht_obj is None:
            logger.debug("No DHT object found, skipping callback setup")
            return

        def handle_temperature_update(temperature: float) -> None:
            """Handle temperature updates from DHT sensor"""
            for thermostat in self.yaml_config["thermostats"].values():
                try:
                    thermostat: ThermostatObject = thermostat
                    thermostat.update_dht_related_status(temperature=temperature)
                except (AttributeError, TypeError, ValueError) as e:
                    logger.error(f"Error updating thermostat with temperature {temperature}: {e}")

        def handle_humidity_update(humidity: float) -> None:
            """Handle humidity updates from DHT sensor"""
            for thermostat in self.yaml_config["thermostats"].values():
                try:
                    thermostat: ThermostatObject = thermostat
                    thermostat.update_dht_related_status(humidity=humidity)
                except (AttributeError, TypeError, ValueError) as e:
                    logger.error(f"Error updating thermostat with humidity {humidity}: {e}")

        # Register the callbacks
        dht_obj.register_temperature_callback(handle_temperature_update)
        dht_obj.register_humidity_callback(handle_humidity_update)

    def load_config(self) -> None:
        """
        Load the entire configuration from YAML files.
        """
        self.yaml_config: dict[str, Any] = {
            "config": {}, "thermostats": {}, "dht": {}, "klok": {}, "fan": {}, "powerbutton": {}
            }
        try:
            config: dict[str, Any] = cast(dict[str, Any], self._load_yaml_file("config.yaml", {}))
            config = self._set_default_config_values(config)
            config = self._upgrade_config(config)
            self.yaml_config["config"] = config

            self._load_thermostats()
            self._load_dht()
            self._load_klok()
            self._load_fan()
            self._load_powerbutton()

            # Set up DHT callbacks after all objects are loaded
            self._setup_dht_callbacks()

            logger.info("Config loaded")
        except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
            logger.exception("CRITICAL! Config file was not loaded")
            raise SystemExit("CRITICAL! Config file was not loaded") from exc

    def _save_resource(self, resource_name: str, path: str) -> None:
        """
        Save a single named resource to its YAML file.

        Args:
            resource_name (str): The resource key (e.g. "dht", "thermostats").
            path (str): The directory path to write the file into.
        """
        file_path: str = path + resource_name + ".yaml"
        dump_dict: dict[str, Any] = {}

        if resource_name in ["dht", "klok", "powerbutton"]:
            obj = self.yaml_config.get(resource_name)
            if obj is not None and hasattr(obj, 'save'):
                saved_data: dict[str, Any] = obj.save()
                if saved_data:
                    dump_dict.update(saved_data)
            elif obj is None and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.debug(f"Removed config file {file_path}")
                    return
                except OSError as e:
                    logger.error(f"Failed to remove config file {file_path}: {e}")
        elif resource_name in ["thermostats", "fan"]:
            for element, obj in self.yaml_config[resource_name].items():
                if element != "0":
                    saved_data = obj.save()
                    if saved_data:
                        dump_dict[obj.id] = saved_data
            if not dump_dict and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.debug(f"Removed config file {file_path}")
                    return
                except OSError as e:
                    logger.error(f"Failed to remove config file {file_path}: {e}")

        _write_yaml(file_path, dump_dict)
        logger.debug("Dump config file " + file_path)

    def save_config(self, backup: bool = False, resource: str = "all") -> None:
        """
        Save the current configuration to YAML files.

        Args:
            backup (bool): Whether to save a backup of the configuration.
            resource (str): The specific resource to save or "all" to save everything.
        """
        path: str = self.configDir + '/'
        if backup:
            path = self.configDir + '/backup/'
            if not os.path.exists(path):
                os.makedirs(path)
        if resource in ["all", "config"]:
            config: dict[str, Any] = self.yaml_config["config"]
            _write_yaml(path + "config.yaml", config)
            logger.debug("Dump config file " + path + "config.yaml")
            if resource == "config":
                return
        all_resources: list[str] = ["thermostats", "dht", "klok", "fan", "powerbutton"]
        save_resources: list[str] = all_resources if resource == "all" else [resource]
        for resource_name in save_resources:
            self._save_resource(resource_name, path)

    def reset_config(self) -> None:
        """
        Reset the configuration to default values.
        """
        self.save_config(backup=True)
        try:
            for yaml_file in Path(self.configDir).glob("*.yaml"):
                os.remove(yaml_file)
        except OSError:
            logger.exception("Something went wrong when deleting the config")
        self.load_config()

    def restore_backup(self) -> None:
        """
        Restore the configuration from a backup.
        """
        try:
            for yaml_file in Path(self.configDir).glob("*.yaml"):
                os.remove(yaml_file)
        except OSError:
            logger.exception("Something went wrong when deleting the config")
        for yaml_file in Path(self.configDir, "backup").glob("*.yaml"):
            shutil.copy(yaml_file, self.configDir)
        self.load_config()

    def download_config(self) -> str:
        """
        Download the current configuration as a zip file.

        Returns:
            str: The path to the zip file containing the configuration.
        """
        self.save_config()
        zip_path = str(Path(self.configDir) / "config.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for yaml_file in Path(self.configDir).glob("*.yaml"):
                if yaml_file.name != "config_debug.yaml":
                    zf.write(yaml_file, yaml_file.name)
        return zip_path

    def download_log(self) -> str:
        """
        Download the log files as a zip file.

        Returns:
            str: The path to the zip file containing the log files.
        """
        zip_path = str(Path(self.configDir) / "server_log.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for log_file in Path(self.runningDir).glob("*.log*"):
                zf.write(log_file, log_file.name)
        return zip_path

    def download_debug(self) -> str:
        """
        Download the debug information as a zip file.

        Returns:
            str: The path to the zip file containing the debug information.
        """
        debug: dict[str, Any] = deepcopy(self.yaml_config["config"])
        info: dict[str, Any] = {}
        info["OS"] = os.uname().sysname
        info["Architecture"] = os.uname().machine
        info["os_version"] = os.uname().version
        info["os_release"] = os.uname().release
        info["Server Version"] = self.serverCreateTime
        info["WebUI Version"] = self.WebUICreateTime
        info["arguments"] = {k: str(v) for k, v in self.argsDict.items()}
        zip_path = str(Path(self.configDir) / "config_debug.zip")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            _write_yaml(str(temp_path / "config_debug.yaml"), debug)
            _write_yaml(str(temp_path / "system_info.yaml"), info)
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for yaml_file in Path(self.configDir).glob("*.yaml"):
                    if yaml_file.name != "config.yaml":
                        zf.write(yaml_file, yaml_file.name)
                for temp_file in temp_path.glob("*.yaml"):
                    zf.write(temp_file, temp_file.name)
                for log_file in Path(self.runningDir).glob("*.log*"):
                    zf.write(log_file, log_file.name)
        return zip_path

    def restart_python(self) -> None:
        """
        Restart the Python process or systemd service.
        """
        try:
            logger.info("restart using systemctl")
            subprocess.run(
                ['sudo', 'systemctl', 'restart', 'raspberry_extension_server.service'],
                check=True)
            return  # Should not reach here if systemctl works
        except subprocess.CalledProcessError as e:
            # If the process was killed by SIGTERM, do nothing (systemd is restarting us)
            if e.returncode == -signal.SIGTERM:
                logger.info(
                    "Process terminated by SIGTERM (expected during systemctl restart)." \
                    "Not falling back to os.execl."
                    )
                sys.exit(0)
            logger.error(f"systemctl restart failed: {e}, falling back to os.execl")
            logger.info(f"restart {sys.executable} with args: {sys.argv}")
            os.execl(sys.executable, sys.executable, *sys.argv)
        except OSError as e:
            logger.error(f"systemctl restart failed: {e}, falling back to os.execl")
            logger.info(f"restart {sys.executable} with args: {sys.argv}")
            os.execl(sys.executable, sys.executable, *sys.argv)
