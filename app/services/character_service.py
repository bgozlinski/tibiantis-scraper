from typing import Dict, List, Optional, Tuple, Any
import logging

from app.schemas.character import character_schema
from app.scraper.tibiantis_scraper import TibiantisScraper
from app.db.models.character import Character
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class CharacterService:
    """
    Service for character-related operations.
    """

    def __init__(self) -> None:
        """Initialize the character service."""
        self.scraper = TibiantisScraper()

    def get_character_data(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get character data from Tibiantis website.

        Args:
            name: Character name to fetch

        Returns:
            Character data dictionary or None if not found

        Raises:
            Exception: If there's an error fetching or processing data
        """
        return self.scraper.get_character_data(character_name=name)

    def get_character_deaths(self, name: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get character death history from Tibiantis website.

        Args:
            name: Character name to fetch deaths for

        Returns:
            List of death records or None if character not found

        Raises:
            Exception: If there's an error fetching or processing data
        """
        return self.scraper.get_character_deaths(character_name=name)

    def add_character(self, name: str) -> Tuple[Dict[str, Any], int]:
        """
        Add a character to the database.

        Args:
            name: Character name to add

        Returns:
            Tuple of (response_dict, status_code)
        """
        character_data = self.scraper.get_character_data(character_name=name)

        if not character_data:
            return {"error": f"Character {name} does not exist on Tibiantis server"}, 404

        db = SessionLocal()

        try:
            existing_character = db.query(Character).filter(Character.name == character_data["name"]).first()

            if existing_character:
                return {"message": f"Character {name} already exists in the database"}, 200
            try:
                # Validate data with schema before creating model instance
                validated_data = character_schema.load(character_data)
                new_character = Character(**validated_data)
                db.add(new_character)
                db.commit()

            except Exception as schema_error:
                # Log the schema validation error but don't expose it directly
                logger.error(f"Schema validation error: {str(schema_error)}")
                raise Exception("Database error processing character data")

            return {"message": f"Character {name} added successfully"}, 201

        except Exception as e:
            db.rollback()
            logger.error(f"Error adding character {name}: {str(e)}")
            return {"error": str(e)}, 500

        finally:
            db.close()
