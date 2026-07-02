"""
This module implements a WebSocket server that streams log messages to connected clients.
"""
import threading
import time
import logging
import socket

from ws4py.server.cherrypyserver import WebSocketPlugin, WebSocketTool
from ws4py.websocket import WebSocket
import cherrypy

import logManager

logger: logging.Logger = logManager.logger.get_logger(__name__)

LOG_FILE = logManager.logger.get_log_file_path()

# Module-level flag to track server state
_SERVER_RUNNING = threading.Event()

class LogWebSocketHandler(WebSocket):
    """
    WebSocket handler that streams log messages to connected clients.
    """
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._running: bool = False
        self._thread: threading.Thread | None = None

    def opened(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self.tail_log)
        self._thread.daemon = True
        self._thread.start()

    def closed(self, code: int, reason: str | None = None) -> None:
        self._running = False

    def tail_log(self) -> None:
        """
        Continuously read the log file and send new lines to the WebSocket client.
        """
        try:
            with open(LOG_FILE, encoding='utf-8') as f:
                f.seek(0, 2)
                while self._running:
                    line: str = f.readline()
                    if line:
                        try:
                            self.send(line)
                        except (OSError, RuntimeError) as e:
                            logger.error(f"Error sending log line: {e}")
                            break
                    else:
                        time.sleep(0.5)
        except (OSError, UnicodeDecodeError) as e:
            logger.error(f"Error tailing log file: {e}")

cherrypy.config.update({'server.socket_host': '0.0.0.0', 'server.socket_port': 9000})
WebSocketPlugin(cherrypy.engine).subscribe()
cherrypy.tools.websocket = WebSocketTool()

class Root:
    """
    Root class for CherryPy WebSocket server.
    """
    @cherrypy.expose
    def index(self) -> str:
        """
        Serve a simple HTML page for testing the WebSocket connection.
        """
        return "WebSocket log server running."

    @cherrypy.expose
    def ws(self) -> None:
        """
        Handle WebSocket connections.
        """

def start_ws_server() -> None:
    """
    Start the CherryPy WebSocket server to stream log messages.
    """
    try:
        cherrypy.log.screen = False
        autoreload = getattr(cherrypy.engine, "autoreload", None)
        if autoreload is not None:
            autoreload.unsubscribe()

        # Check if port is available
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('0.0.0.0', 9000))
        sock.close()

        if result == 0:
            logger.warning("Port 9000 appears to be already in use")
            raise RuntimeError(
                "Port 9000 is already in use. " \
                "Please stop the service using this port before starting the WebSocket server."
                )

        _SERVER_RUNNING.set()

        # This is a blocking call - the server runs here
        cherrypy.quickstart(Root(), '/', config={
            '/ws': {
                'tools.websocket.on': True,
                'tools.websocket.handler_cls': LogWebSocketHandler
            }
        })
    except (RuntimeError, OSError) as e:
        logger.error(f"Failed to start CherryPy WebSocket server: {e}")
        logger.exception("Full traceback:")
        raise
    finally:
        _SERVER_RUNNING.clear()

def stop_ws_server() -> None:
    """
    Gracefully stop the CherryPy WebSocket server.
    """
    try:
        if _SERVER_RUNNING.is_set():
            logger.info("Stopping CherryPy WebSocket server...")
            cherrypy.engine.exit()
            _SERVER_RUNNING.clear()
            logger.info("CherryPy WebSocket server stopped.")
        else:
            logger.info("CherryPy WebSocket server is not running.")
    except (RuntimeError, OSError) as e:
        logger.error(f"Error stopping CherryPy WebSocket server: {e}")
        logger.exception("Full traceback:")
