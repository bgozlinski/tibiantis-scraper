from flask import Flask, jsonify
from app.config import get_config
from app.routes.bedmage_routes import bedmage_bp
from app.routes.character_routes import character_bp
import logging
from app.utils.error_handlers import register_error_handlers
from app.utils.scheduler import init_scheduler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    logger.info("Application startup complete. Performing startup tasks.")

    # Register blueprints
    app.register_blueprint(character_bp, url_prefix='/api/v1/characters')
    app.register_blueprint(bedmage_bp, url_prefix='/api/v1/bedmages')

    # Register error handlers
    register_error_handlers(app)

    # Initialize and start scheduler
    init_scheduler(app)

    @app.route("/")
    def index():
        return jsonify({"message": "Tibiantis Scraper API"}), 200

    return app

app = create_app()
