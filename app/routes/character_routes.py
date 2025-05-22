from flask import Blueprint, jsonify
from app.scraper.tibiantis_scraper import TibiantisScraper
from app.db.models import Character
from app.db.session import SessionLocal

character_bp = Blueprint("character", __name__)

@character_bp.route("/scrap/data/<name>")
def scrap_character(name):
    scraper = TibiantisScraper()
    character_data = scraper.get_character_data(character_name=name)

    return character_data

@character_bp.route("/scrap/death/<name>")
def scrap_character_deaths(name):
    scraper = TibiantisScraper()
    character_deaths = scraper.get_character_deaths(character_name=name)

    return character_deaths

@character_bp.route("/add/<name>")
def add_character(name):
    scraper = TibiantisScraper()
    character_data = scraper.get_character_data(character_name=name)

    if not character_data:
        return jsonify({"error": f"Character {name} does not exist on Tibiantis server"}), 404

    db = SessionLocal()

    try:
        existing_character = db.query(Character).filter(Character.name == character_data["name"]).first()

        if existing_character:
            return jsonify({"message": f"Character {name} already exists in the database"}), 200

        new_character = Character(**character_data)
        db.add(new_character)

        db.commit()

        return jsonify({"message": f"Character {name} added successfully"}), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Error adding character {name}: {e}"}), 500

    finally:
        db.close()



