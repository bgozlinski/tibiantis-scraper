from flask import Flask
from app.config import DevelopmentConfig, ProductionConfig
from flask import Blueprint
from app.routes.character_routes import character_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(DevelopmentConfig)

    print("Application startup complete. Performing startup tasks.")

    app.register_blueprint(character_bp, url_prefix='/characters')

    @app.route("/")
    async def index():
        return "Hello, World!"

    return app

app = create_app()

