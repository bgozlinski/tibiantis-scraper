from datetime import datetime
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
            List of death records or None if character is not found

        Raises:
            Exception: If there's an error fetching or processing data
        """
        return self.scraper.get_character_deaths(character_name=name)

    def get_online_characters_list(self) -> Optional[List[str]]:
        """
        Get a list of characters currently online on Tibiantis server.

        Returns:
            List of character names or None if fetching fails

        Raises:
            Exception: If there's an error fetching or processing data
        """
        return self.scraper.get_online_characters_list()

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

    def get_all_characters_from_db(self) -> Optional[List[str]]:
        """
        Get a list of all character names from the database.

        Returns:
            List of character names stored in the database
        """
        db = SessionLocal()
        try:
            characters = db.query(Character.name).all()
            return [character[0] for character in characters]
        except Exception as e:
            logger.error(f"Error fetching characters from database: {str(e)}")
            raise Exception(f"Error fetching characters from database: {str(e)}")
        finally:
            db.close()

    def add_new_online_characters(self) -> Dict[str, Any]:
        """
        Add only online characters that are not already in the database.

        Returns:
            Dictionary with results of the operation
        """
        # Get a list of online characters
        online_characters = self.get_online_characters_list()

        if online_characters is None:
            raise Exception("Failed to fetch online characters")

        # Get list of characters already in the database
        db_characters = self.get_all_characters_from_db()

        # Find characters that are online but not in the database
        new_characters = [char for char in online_characters if char not in db_characters]

        results = {
            "total_online": len(online_characters),
            "already_in_db": len(online_characters) - len(new_characters),
            "new_characters": len(new_characters),
            "added": 0,
            "failed": 0,
            "failures": []
        }

        # Add new characters to the database
        for character_name in new_characters:
            try:
                result, status_code = self.add_character(character_name)

                if status_code == 201:  # Created
                    results["added"] += 1
                else:
                    results["failed"] += 1
                    results["failures"].append({
                        "name": character_name,
                        "reason": result.get("error", "Unknown error")
                    })
            except Exception as e:
                results["failed"] += 1
                results["failures"].append({
                    "name": character_name,
                    "reason": str(e)
                })

        return results


    def get_minutes_sice_last_login(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Calculate minutes since the character's last login.

        Args:
            name: Character name to check

        Returns:
            Dictionary with character data and minutes since last login,
            or None if character not found
        """

        characer_data = self.get_character_data(name)

        if not characer_data or not characer_data.get("last_login"):
            return None

        # Calculate minutes since last login
        now = datetime.now()
        last_login = characer_data["last_login"]
        time_diff = (now - last_login).total_seconds() / 60

        result = {
            **characer_data,
            "minutes_since_last_login": int(time_diff),
            "can_login": time_diff >= 100
        }

        return result

