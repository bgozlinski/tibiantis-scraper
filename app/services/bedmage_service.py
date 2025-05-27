import logging

from app.db.models import Character
from app.db.session import SessionLocal
from typing import Tuple, Any, Dict, List, Optional
from app.db.models.bedmage_character import Bedmage

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
