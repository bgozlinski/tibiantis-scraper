from flask import Flask
from app.config import DevelopmentConfig, ProductionConfig


def create_app():
    app = Flask(__name__)
    app.config.from_object(DevelopmentConfig)

    print("Application startup complete. Performing startup tasks.")

    @app.route("/")
    async def index():
        return "Hello, World!"

    return app

app = create_app()

