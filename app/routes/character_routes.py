from flask import Blueprint, jsonify, Response, request
from app.scraper.tibiantis_scraper import TibiantisScraper
from app.db.models import Character
from app.db.session import SessionLocal
from app.services.character_service import CharacterService
import logging

logger = logging.getLogger(__name__)
character_bp = Blueprint("character", __name__)
character_service = CharacterService()

@character_bp.route("/<name>", methods=["GET"])
def get_character(name: str) -> Response:
    """
    Get character data from Tibiantis website.

    Args:
        name: Character name to fetch

    Returns:
        JSON response with character data
    """
    try:
        character_data = character_service.get_character_data(name)
        if not character_data:
            return jsonify({"error": f"Character not found"}), 404

        return jsonify({"data": character_data}), 200
    except Exception as e:
        logger.error(f"Error fetching character {name}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@character_bp.route("/<name>/deaths", methods=["GET"])
def get_character_deaths(name: str) -> Response:
    """
    Get character death history from Tibiantis website.

    Args:
        name: Character name to fetch deaths for

    Returns:
        JSON response with death history
    """
    try:
        character_deaths = character_service.get_character_deaths(name)

        if character_deaths is None:
            return jsonify({"error": f"Character {name} does not exist on Tibiantis server"}), 404

        return jsonify({"data": character_deaths}), 200
    except Exception as e:
        logger.error(f"Error fetching character deaths for {name}: {str(e)}")
        return jsonify({"error": str(e)}), 500



@character_bp.route("/add/<name>", methods=["POST"])
def add_character(name: str) -> Response:
    """
    Add a character to the database.

    Request body:
        name: Character name to add

    Returns:
        JSON response with result
    """
    try:
        data = request.get_json()
        if not data or "name" not in data:
            return jsonify({"error": "Name is required"}), 400

        if data["name"] != name:
            return jsonify({"error": "Name in URL must match name in request body"}), 400

        result, status_code = character_service.add_character(name)
        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Error adding character {str(e)}")
        return jsonify({"error": str(e)}), 500
