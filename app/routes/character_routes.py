from flask import Blueprint
from app.scraper.tibiantis_scraper import TibantisScraper

character_bp = Blueprint("character", __name__)

@character_bp.route("/scrap/data/<name>")
def scrap_character(name):
    scraper = TibantisScraper()
    character_data = scraper.get_character_data(character_name=name)

    return character_data

@character_bp.route("/scrap/death/<name>")
def scrap_character_deaths(name):
    scraper = TibantisScraper()
    character_deaths = scraper.get_character_deaths(character_name=name)

    return character_deaths
