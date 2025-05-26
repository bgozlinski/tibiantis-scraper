from flask import Blueprint, jsonify, Response, request
from typing import Tuple
from app.schemas.character import (
    character_response_schema,
    character_request_schema,
    character_with_deaths_schema,
    character_login_time_schema
)
from app.schemas.death import deaths_schema
from app.services.character_service import CharacterService
import logging

logger = logging.getLogger(__name__)
character_bp = Blueprint("character", __name__)
character_service = CharacterService()

@character_bp.route("/<name>", methods=["GET"])
def get_character(name: str) -> Tuple[Response, int]:
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

        # Serialize the response using schema
        result = character_response_schema.dump(character_data)
        return jsonify({"data": result}), 200
    except Exception as e:
        logger.error(f"Error fetching character {name}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@character_bp.route("/<name>/full", methods=["GET"])
def get_full_character(name: str) -> Tuple[Response, int]:
    """
    Get complete character data including death history.

    Args:
        name: Character name to fetch

    Returns:
        JSON response with character data and death history
    """
    try:
        character_data = character_service.get_character_data(name)
        if not character_data:
            return jsonify({"error": f"Character not found"}), 404

        character_deaths = character_service.get_character_deaths(name)

        # Combine character data with deaths
        full_data = {**character_data, "deaths": character_deaths or []}

        result = character_with_deaths_schema.dump(full_data)
        return jsonify({"data": result}), 200

    except Exception as e:
        logger.error(f"Error fetching full character data for {name}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@character_bp.route("/<name>/deaths", methods=["GET"])
def get_character_deaths(name: str) -> Tuple[Response, int]:
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

        # Serialize the response using schema
        result = deaths_schema.dump(character_deaths)
        return jsonify({"data": result}), 200
    except Exception as e:
        logger.error(f"Error fetching character deaths for {name}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@character_bp.route("/add/<name>", methods=["POST"])
def add_character(name: str) -> Tuple[Response, int]:
    """
    Add a character to the database.

    Request body:
        name: Character name to add

    Returns:
        JSON response with result
    """
    try:
        # Check for missing name first
        if not request.json or "name" not in request.json:
            return jsonify({"error": "Name is required"}), 400

        # Validate request data using schema
        errors = character_request_schema.validate(request.json)
        if errors:
            return jsonify({"error": errors}), 400

        if not request.json or "name" not in request.json:
            return jsonify({"error": "Name is required"}), 400

        if request.json["name"] != name:
            return jsonify({"error": "Name in URL must match name in request body"}), 400

        result, status_code = character_service.add_character(name)
        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Error adding character {str(e)}")
        return jsonify({"error": str(e)}), 500

@character_bp.route("/online", methods=["GET"])
def get_online_characters() -> Tuple[Response, int]:
    """
    Get a list of characters currently online on Tibiantis server.

    Returns:
        JSON response with a list of online character names
    """
    try:
        online_characters = character_service.get_online_characters_list()

        if online_characters is None:
            return jsonify({"error": "Failed to fetch online characters"}), 500

        return jsonify({"data": online_characters}), 200

    except Exception as e:
        logger.error(f"Error fetching online characters: {str(e)}")
        return jsonify({"error": str(e)}), 500


@character_bp.route("/online/add", methods=["POST"])
def add_online_characters() -> Tuple[Response, int]:
    """
    Add only online characters that are not already in the database.

    Returns:
        JSON response with results of the operation
    """
    try:
        # Use the new service method that only adds characters not already in the database
        results = character_service.add_new_online_characters()

        return jsonify({"data": results}), 200

    except Exception as e:
        logger.error(f"Error adding online characters: {str(e)}")
        return jsonify({"error": str(e)}), 500


@character_bp.route("/<name>/login-time", methods=["GET"])
def get_character_login_time(name: str) -> Tuple[Response, int]:
    """
    Get character data with minutes since last login.

    Args:
        name: Character name to check

    Returns:
        JSON response with character data and login time information
    """
    try:
        login_time_data = character_service.get_minutes_since_last_login(name)

        if not login_time_data:
            return jsonify({"error": f"Character not found or no login data available"}), 404

        # Serialize the response using schema
        result = character_login_time_schema.dump(login_time_data)
        return jsonify({"data": result}), 200

    except Exception as e:
        logger.error(f"Error fetching character login time for {name}: {str(e)}")
        return jsonify({"error": str(e)}), 500


