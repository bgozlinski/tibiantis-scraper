from flask import Blueprint, jsonify, Response, request
from typing import Tuple

from app.services.bedmage_service import BedmageService
import logging

logger = logging.getLogger(__name__)


def create_bedmage_blueprint(bedmage_service: BedmageService):
    """
    Create the bedmage blueprint with injected service.

    Args:
        bedmage_service: The bedmage service to use

    Returns:
        The bedmage blueprint
    """
    bedmage_bp = Blueprint("bedmage", __name__)

    @bedmage_bp.route("/add/<name>", methods=["POST"])
    def add_bedmage_character(name: str) -> Tuple[Response, int]:
        """
        Add a character to bedmage monitoring.

        Request body:
            character_name: Character name to add to bedmage monitoring

        Returns:
            JSON response with a result
        """
        try:
            result, status_code = bedmage_service.add_bedmage_character(character_name=name)
            return jsonify(result), status_code

        except Exception as e:
            logger.error(f"Error adding bedmage character: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @bedmage_bp.route("/<name>/timer", methods=["GET"])
    def get_bedmage_timer(name: str) -> Tuple[Response, int]:
        """
        Get bedmage timer information for a character.

        Args:
            name: Character name to check

        Returns:
            JSON response with timer information including
            - name: Name of the player
            - minutes_since_last_login: Time since last login in minutes
            - can_login: Boolean indicating if the player can login (True if time >= 100 minutes)
        """
        try:
            result, status_code = bedmage_service.get_bedmage_timer(character_name=name)
            return jsonify(result), status_code

        except Exception as e:
            logger.error(f"Error adding bedmage character: {str(e)}")
            return jsonify({"error": str(e)}), 500

    return bedmage_bp




