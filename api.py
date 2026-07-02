#!/usr/bin/env python3
"""
Main entry point for the Eqiva Smart Radiator Thermostat API
"""
from threading import Thread
import os
import signal
from typing import Any
import time
import logging
from flask import Flask
from werkzeug.serving import WSGIRequestHandler

import logManager
logManager.logger.enable_file_logging()
from flask_ui import create_app
from services import log_ws, scheduler, state_fetch, update_manager
import config_manager

SERVER_CONFIG = config_manager.SERVER_CONFIG
logger: logging.Logger = logManager.logger.get_logger(__name__)
werkzeug_logger: logging.Logger = logManager.logger.get_logger("werkzeug")
cherrypy_logger: logging.Logger = logManager.logger.get_logger("cherrypy")
WSGIRequestHandler.protocol_version = "HTTP/1.1"

# Create app using factory pattern (diyHue style)
app: Flask = create_app(SERVER_CONFIG)

def run_http(bind_ip: str, host_ip: str, host_http_port: int) -> None:
    """Run the HTTP server"""
    logger.debug(f"Starting HTTP server on {bind_ip}:{host_http_port}")
    logger.info(f"You can access the server on {host_ip}:{host_http_port}")
    app.run(host=bind_ip, port=host_http_port)

def handle_exit(signum: int, frame: Any) -> None:
    """Handle exit signals"""
    logger.info(f"Received signal {signum} on {frame}, shutting down gracefully...")

    # Stop all services immediately using threading events
    state_fetch.stop_all_services()

    # Clean up specific services
    state_fetch.disconnect_thermostats()
    scheduler.stop_scheduler()
    log_ws.stop_ws_server()

    # Give threads a moment to exit gracefully
    time.sleep(2)

    os._exit(0)

def setup_signal_handlers() -> None:
    """Setup signal handlers for graceful shutdown"""
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

def main():
    """Main entry point for the application"""
    try:
        setup_signal_handlers()
        bind_ip: str = getattr(SERVER_CONFIG, "bindIp", "0.0.0.0")
        host_ip: str = getattr(SERVER_CONFIG, "ip", "0.0.0.0")
        host_http_port: int = getattr(SERVER_CONFIG, "httpPort", 5000)
        update_manager.startup_check()

        Thread(target=state_fetch.sync_with_thermostats_threaded).start()
        Thread(target=state_fetch.run_dht_service).start()
        Thread(target=state_fetch.run_fan_service).start()
        Thread(target=state_fetch.run_klok_service).start()
        Thread(target=state_fetch.run_powerbutton_service).start()
        Thread(target=scheduler.run_scheduler).start()
        Thread(target=log_ws.start_ws_server).start()
        run_http(bind_ip, host_ip, host_http_port)
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down gracefully...")
        handle_exit(signal.SIGINT, None)
    except (OSError, RuntimeError) as e:
        logger.error(f"Unexpected error occurred: {e}")
        handle_exit(signal.SIGTERM, None)
    finally:
        logger.info("Application shutdown complete.")

if __name__ == '__main__':
    main()
