from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import logging
from app.schemas.character import character_schema
from app.db.models.character import Character
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class CharacterService:
    """
    Service for character-related operations.
    """

    def __init__(self, scraper=None) -> None:
        """
        Initialize the character service.

        Args:
            scraper: TibiantisScraper instance (injected)
        """
        from app.scraper.tibiantis_scraper import TibiantisScraper
        self.scraper = scraper or TibiantisScraper()

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

    def get_character_from_db(self, name:str) -> Optional[Character]:
        """
        Get a character from the database by name.

        Args:
            name: Character name to fetch

        Returns:
            Character object or None if not found
        """
        db = SessionLocal()
        try:
            character = db.query(Character).filter(Character.name == name).scalar()
            return character
        except Exception as e:
            logger.error(f"Error fetching character {name} from database: {str(e)}")
            raise Exception(f"Error fetching character from database: {str(e)}")
        finally:
            db.close()

    def get_all_characters_full_from_db(self) -> List[Character]:
        """
        Get all characters from the database with full data.

        Returns:
            List of Character objects
        """
        db = SessionLocal()
        try:
            characters = db.query(Character).all()
            return characters
        except Exception as e:
            logger.error(f"Error fetching all characters from database: {str(e)}")
            raise Exception(f"Error fetching all characters from database: {str(e)}")
        finally:
            db.close()

    def update_character(self, character: Character, new_data: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """
        Update a character in the database with new data.

        Args:
            character: Character object to update
            new_data: New character data

        Returns:
            Tuple of (response_dict, status_code)
        """
        db = SessionLocal()
        try:
            # Validate data with schema before updating
            validated_data = character_schema.load(new_data)

            # Update character fields
            for key, value in validated_data.items():
                # Skip id, created_at, and updated_at fields
                if key not in ['id', 'created_at', 'updated_at']:
                    setattr(character, key, value)

            db.add(character)
            db.commit()

            logger.info(f"Character {character.name} updated successfully")
            return {"message": f"Character {character.name} updated successfully"}, 200

        except Exception as e:
            db.rollback()
            logger.error(f"Error updating character {character.name}: {str(e)}")
            return {"error": str(e)}, 500

        finally:
            db.close()

    def check_character_for_updates(self, character: Character) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if a character needs to be updated by comparing DB data with website data.

        Args:
            character: Character object from database

        Returns:
            Tuple of (needs_update, new_data)
        """
        # Get latest data from website
        new_data = self.get_character_data(character.name)

        if not new_data:
            return False, None

        # Check if any fields have changed
        needs_update = False
        fields_to_check = [
            'sex', 'vocation', 'level', 'world', 'residence',
            'house', 'guild_membership', 'last_login', 'comment', 'account_status'
        ]

        for field in fields_to_check:
            db_value = getattr(character, field)
            web_value = new_data.get(field)

            # Special handling for datetime fields
            if field == 'last_login' and db_value and web_value:
                # Compare only date parts, not time
                if db_value.date() != web_value.date():
                    needs_update = True
                    break
            elif db_value != web_value:
                needs_update = True
                break

        return needs_update, new_data

    def update_all_characters(self) -> Dict[str, Any]:
        """
        Check all characters in the database for updates and update if needed.

        Returns:
            Dictionary with results of the operation
        """
        # Get all characters from a database
        characters = self.get_all_characters_full_from_db()

        results = {
            "total_characters": len(characters),
            "checked": 0,
            "updated": 0,
            "failed": 0,
            "not_found": 0,
            "no_changes": 0,
            "failures": []
        }

        # Check each character for updates
        for character in characters:
            try:
                results["checked"] += 1
                needs_update, new_data = self.check_character_for_updates(character)

                if not new_data:
                    results["not_found"] += 1
                    results["failures"].append({
                        "name": character.name,
                        "reason": "Character not found on Tibiantis server"
                    })
                    continue

                if needs_update:
                    result, status_code = self.update_character(character, new_data)

                    if status_code == 200:
                        results["updated"] += 1
                    else:
                        results["failed"] += 1
                        results["failures"].append({
                            "name": character.name,
                            "reason": result.get("error", "Unknown error")
                        })
                else:
                    results["no_changes"] += 1

            except Exception as e:
                results["failed"] += 1
                results["failures"].append({
                    "name": character.name,
                    "reason": str(e)
                })

        return results

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
            existing_character = db.query(Character).filter(
                Character.name == character_data["name"]).scalar()

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

            logger.info(f"Character {name} added to database")
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


    def get_minutes_since_last_login(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Calculate minutes since the character's last login.

        Args:
            name: Character name to check

        Returns:
            Dictionary with character data and minutes since last login,
            or None if character not found
        """

        character_data = self.get_character_data(name)

        if not character_data or not character_data.get("last_login"):
            return None

        # Calculate minutes since last login
        now = datetime.now()
        last_login = character_data["last_login"]
        time_diff = (now - last_login).total_seconds() / 60

        result = {
            **character_data,
            "minutes_since_last_login": int(time_diff),
            "can_login": time_diff >= 100
        }

        return result

