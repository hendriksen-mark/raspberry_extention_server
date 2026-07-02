"""
This module provides functions to check for updates on GitHub.
"""
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

import logging
import requests

import logManager

import config_manager
from .github_installer import install_github_updates

SERVER_CONFIG: dict[str, Any] = config_manager.SERVER_CONFIG.yaml_config
logger: logging.Logger = logManager.logger.get_logger(__name__)

BASE_URL: str = "https://api.github.com/repos/hendriksen-mark/raspberry_extension_server"

def github_check() -> None:
    """
    Check for updates on GitHub for both the main server repository and the UI repository.
    Update the server configuration based on the availability of updates.
    """
    creation_time: str = get_file_creation_time("api.py")
    publish_time: str = get_github_publish_time(f"{BASE_URL}/branches/{SERVER_CONFIG['config']['system']['branch']}")

    logger.debug(f"creation_time server : {creation_time}")
    logger.debug(f"publish_time  server : {publish_time}")

    if publish_time > creation_time:
        logger.info("update on github")
        SERVER_CONFIG["config"]["swupdate2"]["state"] = "allreadytoinstall"
    elif github_ui_check():
        logger.info("UI update on github")
        SERVER_CONFIG["config"]["swupdate2"]["state"] = "anyreadytoinstall"
    else:
        logger.info("no update for server or UI on github")
        SERVER_CONFIG["config"]["swupdate2"]["state"] = "noupdates"

    SERVER_CONFIG["config"]["swupdate2"]["checkforupdate"] = False

def github_ui_check() -> bool:
    """
    Check for updates on the GitHub UI repository.
    
    Returns:
        bool: True if there is a new update available, False otherwise.
    """
    creation_time: str = get_file_creation_time("flask_ui/templates/index.html")
    publish_time: str = get_github_publish_time(f"{BASE_URL}_ui/releases/latest")

    logger.debug(f"creation_time UI : {creation_time}")
    logger.debug(f"publish_time  UI : {publish_time}")

    return publish_time > creation_time

def get_file_creation_time(filepath: str) -> str:
    """
    Get the creation time of a file.
    
    Args:
        filepath (str): The path to the file.
    
    Returns:
        str: The creation time of the file in the format "%Y-%m-%d %H".
    """
    try:
        mtime: float = os.stat(filepath).st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H")
    except OSError as e:
        logger.error(f"Error getting file creation time: {e}")
        return "2999-01-01 01"

def get_github_publish_time(url: str) -> str:
    """
    Get the publish time of the latest commit or release from a GitHub repository.
    
    Args:
        url (str): The API URL to fetch the publish time from.
    
    Returns:
        str: The publish time in the format "%Y-%m-%d %H".
    """
    try:
        response: requests.Response = requests.get(url, timeout=10)
        response.raise_for_status()
        device_data: dict[str, Any] = response.json()
        if "commit" in device_data:
            commit_date = device_data["commit"]["commit"]["author"]["date"]
            return datetime.strptime(commit_date, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H")
        if "published_at" in device_data:
            publish_date = device_data["published_at"]
            return datetime.strptime(publish_date, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H")
        logger.error("Unexpected GitHub API response format")
        return "1970-01-01 00:00:00"
    except requests.RequestException as e:
        logger.error(f"No connection to GitHub: {e}")
        # Set state to unknown when there's no connection to update server
        SERVER_CONFIG["config"]["swupdate2"]["state"] = "unknown"
        return "1970-01-01 00:00:00"

def update_swupdate2_timestamps() -> None:
    """
    Update the timestamps for the last change and last install in the server configuration.
    """
    current_time: str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    SERVER_CONFIG["config"]["swupdate2"]["lastchange"] = current_time

def github_install() -> None:
    """
    Install updates from GitHub if they are ready to be installed.
    """
    if SERVER_CONFIG["config"]["swupdate2"]["state"] in ["allreadytoinstall", "anyreadytoinstall"]:
        config_manager.SERVER_CONFIG.save_config()
        state = SERVER_CONFIG['config']['swupdate2']['state']
        branch = SERVER_CONFIG['config']['system']['branch']
        try:
            success = install_github_updates(state, branch)
            if success:
                logger.info("Update installation successful, restarting server")
                SERVER_CONFIG["config"]["swupdate2"]["state"] = "noupdates"
                SERVER_CONFIG["config"]["swupdate2"]["install"] = False
                config_manager.SERVER_CONFIG.restart_python()
                # Code after restart_python() will not execute
            else:
                logger.error("Update installation failed")
                SERVER_CONFIG["config"]["swupdate2"]["state"] = "unknown"
        except (subprocess.SubprocessError, OSError, ValueError, requests.RequestException) as e:
            logger.error(f"Error during update installation: {e}")
            SERVER_CONFIG["config"]["swupdate2"]["state"] = "unknown"

def startup_check() -> None:
    """
    Perform a startup check for updates.
    """
    if SERVER_CONFIG["config"]["swupdate2"]["install"]:
        SERVER_CONFIG["config"]["swupdate2"]["install"] = False
        update_swupdate2_timestamps()
    github_check()
