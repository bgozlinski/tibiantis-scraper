from flask import Flask, jsonify


def register_error_handlers(app: Flask) -> None:
    """
    Register error handlers for the Flask application.

    Args:
        app: Flask application instance
    """

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(500)
    def server_error(error):
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({"error": "Bad request"}), 400
