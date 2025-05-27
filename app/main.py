from flask import Flask, jsonify
from app.config import get_config
from app.routes.bedmage_routes import create_bedmage_blueprint
from app.routes.character_routes import create_character_blueprint
import logging
from app.utils.error_handlers import register_error_handlers
from app.utils.scheduler import init_scheduler
from app.utils.di_container import DIContainer
from app.utils.service_provider import register_services
from app.services.character_service import CharacterService
from app.services.bedmage_service import BedmageService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    # Create and configure the dependency injection container
    container = DIContainer()
    register_services(container)

    # Store the container in the app for access in routes
    app.container = container

    logger.info("Application startup complete. Performing startup tasks.")

    # Register blueprints with injected services
    character_service = container.get(CharacterService)
    bedmage_service = container.get(BedmageService)

    app.register_blueprint(
        create_character_blueprint(character_service),
        url_prefix='/api/v1/characters'
    )
    app.register_blueprint(
        create_bedmage_blueprint(bedmage_service),
        url_prefix='/api/v1/bedmages'
    )

    # Register error handlers
    register_error_handlers(app)

    # Initialize and start scheduler
    init_scheduler(app)

    @app.route("/")
    def index():
        return jsonify({"message": "Tibiantis Scraper API"}), 200

    return app

app = create_app()
