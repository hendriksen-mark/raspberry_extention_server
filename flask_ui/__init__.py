"""
API module with Flask app factory and resource registration
Following diyHue architectural patterns
"""
import os
import logging
from typing import Any, cast

from flask import Flask, Request
from flask_cors import CORS
from flask_restful import Api
from werkzeug.security import check_password_hash
import logManager
import flask_login
from flask_ui.core import User  # dummy import for flask_login module
from flask_ui.core.views import core
from flask_ui.error_pages.handlers import error_pages
from .system_routes import SystemRoute
from .dht_routes import DHTRoute
from .thermostat_routes import ThermostatRoute
from .klok_routes import KlokRoute
from .config_routes import ConfigRoute
from .fan_routes import FanRoute
from .powerbutton_routes import PowerButtonRoute


logger: logging.Logger = logManager.logger.get_logger(__name__)


def create_app(server_config) -> Flask:
    """
    App factory function following diyHue pattern
    """
    yaml_config: dict[str, Any] = server_config.yaml_config if hasattr(server_config, 'yaml_config') else server_config
    root_dir: str = server_config.runningDir

    template_dir: str = os.path.join(root_dir, 'flask_ui', 'templates')
    static_dir: str = os.path.join(root_dir, 'flask_ui', 'assets')

    if not os.path.exists(template_dir):
        logger.error(f"Template directory {template_dir} does not exist.")
        raise FileNotFoundError(f"Template directory {template_dir} does not exist.")
    if not os.path.exists(static_dir):
        logger.error(f"Static directory {static_dir} does not exist.")
        raise FileNotFoundError(f"Static directory {static_dir} does not exist.")
    if "index.html" not in os.listdir(template_dir):
        logger.error(f"index.html not found in {template_dir}.")
        raise FileNotFoundError(f"index.html not found in {template_dir}.")

    app: Flask = Flask(__name__,
                       template_folder=template_dir,
                       static_url_path="/assets",
                       static_folder=static_dir)

    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', os.urandom(24))
    app.config['RESTFUL_JSON'] = {'ensure_ascii': False}

    # CORS setup
    CORS(app, resources={r"*": {"origins": "*"}})

    # Flask-Login setup
    login_manager: flask_login.LoginManager = flask_login.LoginManager()
    login_manager.init_app(app)
    cast(Any, login_manager).login_view = "core.login"

    @login_manager.user_loader
    def user_loader(email: str) -> User | None:
        if email not in yaml_config["config"]["users"]:
            return None
        user: User = User()
        setattr(user, "id", email)
        return user

    @login_manager.request_loader
    def request_loader(request: Request) -> User | None:

        email: str | None = request.form.get('email')
        if email is None:
            return None
        if email not in yaml_config["config"]["users"]:
            return None
        password: str | None = request.form.get('password')
        if password is None:
            return None
        user: User = User()
        setattr(user, "id", email)
        logger.info(f"Authentication attempt for user: {email}")
        if not check_password_hash(
            password,
            yaml_config["config"]["users"][email]["password"]
        ):
            return None
        return user

    # Flask-RESTful API setup
    api: Api = Api(app)

    # Register routes with both optional and required resource patterns
    api.add_resource(SystemRoute,       '/system/',
                                        '/system/<string:resource>',
                                        strict_slashes=False)
    api.add_resource(DHTRoute,          '/dht/',
                                        '/dht/<string:resource>',
                                        strict_slashes=False)
    api.add_resource(ThermostatRoute,   '/<string:mac>/',
                                        '/<string:mac>/<string:resource>',
                                        '/<string:mac>/<string:resource>/<string:value>',
                                        strict_slashes=False)
    api.add_resource(KlokRoute,         '/klok/',
                                        '/klok/<string:resource>',
                                        '/klok/<string:resource>/<string:value>',
                                        strict_slashes=False)
    api.add_resource(ConfigRoute,       '/config/',
                                        '/config/<string:resource>',
                                        strict_slashes=False)
    api.add_resource(FanRoute,          '/fan/',
                                        '/fan/<string:fan_id>',
                                        '/fan/<string:fan_id>/<string:resource>',
                                        strict_slashes=False)
    api.add_resource(PowerButtonRoute,  '/powerbutton/',
                                        '/powerbutton/<string:resource>',
                                        strict_slashes=False)

    # Register web interface blueprints
    app.register_blueprint(core)
    app.register_blueprint(error_pages)

    return app
