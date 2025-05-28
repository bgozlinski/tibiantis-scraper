import logging

from app.db.session import SessionLocal
from typing import Tuple, Any, Dict, List, Optional
from app.db.models.bedmage_character import Bedmage
from app.db.models.character import Character

logger = logging.getLogger(__name__)


class BedmageService:
    """
    Service for bedmage-related operations.
    """
    def __init__(self, character_service=None) -> None:
        from app.services.character_service import CharacterService
        self.character_service = character_service or CharacterService()

    def add_bedmage_character(self, character_name: str) ->Tuple[Dict[str, Any], int]:
        """
        Add a character to bedmage monitoring.

        Args:
            character_name: Character name to add to bedmage monitoring

        Returns:
            Tuple of (response_dict, status_code)
        """
        db = SessionLocal()

        try:
            # First, check if the character exists in the database
            character = db.query(Character).filter(Character.name == character_name).scalar()

            if not character:
                # Add character to characters Table DB
                result, status_code = self.character_service.add_character(character_name)

                # If character was not added successfully, return the error
                if status_code != 201 and status_code != 200:
                    return result, status_code

                # Get newly added character
                character = db.query(Character).filter(Character.name == character_name).scalar()

            bedmage = db.query(Bedmage).filter(
                Bedmage.character_name == character_name
            ).scalar()

            if bedmage:
                return {"message": f"Character {character_name} is already being monitored"}, 200

            new_bedmage = Bedmage(character_name=character_name)
            db.add(new_bedmage)
            db.commit()

            logger.info(f"Character {character_name} added to bedmage monitoring")
            return {"message": f"Character {character_name} added to bedmage monitoring"}, 201

        except Exception as e:
            db.rollback()
            logger.error(f"Error adding character {character_name} to bedmage monitoring: {str(e)}")
            return {"error": str(e)}, 500

        finally:
            db.close()


    def get_bedmage_characters(self) -> Optional[List[Dict[str, Any]]]:
        """
        Get all characters being monitored for bedmage.

        Returns:
            List of bedmage monitor records
        """
        db = SessionLocal()

        try:
            bedmages = db.query(Bedmage).all()
            result = []

            for bedmage in bedmages:
                result.append({
                    "id": bedmage.id,
                    "character_name": bedmage.character_name
                })

            return result

        except Exception as e:
            logger.error(f"Error fetching bedmage characters: {str(e)}")
            raise Exception(f"Error fetching bedmage characters: {str(e)}")

        finally:
            db.close()

    def get_bedmage_timer(self, character_name: str) -> Tuple[Optional[Dict[str, Any]], int]:
        """
        Get bedmage timer information for a character.

        Args:
            character_name: Character name to check

        Returns:
            Tuple of (response_dict, status_code)
            The response_dict contains:
            - name: Name of the player
            - minutes_since_last_login: Time since last login in minutes
            - can_login: Boolean indicating if the player can login (True if time >= 100 minutes)
        """
        db = SessionLocal()

        try:
            # Check if the bedmage is in the bedmages table
            bedmage = db.query(Bedmage).filter(Bedmage.character_name == character_name).scalar()
            if not bedmage:
                return {"error": f"Character {character_name} is not being monitored"}, 404

            # Get character data and minutes since last login
            login_data = self.character_service.get_minutes_since_last_login(character_name)

            if not login_data:
                return {"error": f"Could not retrieve login data for character {character_name}"}, 500

            # Extract the required information
            result = {
                "name": character_name,
                "minutes_since_last_login": login_data["minutes_since_last_login"],
                "can_login": login_data["can_login"]  # True if time >= 100 minutes
            }

            return result, 200


        except Exception as e:
            logger.error(f"Error fetching bedmage timer for character {character_name}: {str(e)}")
            return {"error": str(e)}, 500

        finally:
            db.close()
