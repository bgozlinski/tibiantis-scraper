# app/utils/service_provider.py
from app.utils.di_container import DIContainer
from app.scraper.tibiantis_scraper import TibiantisScraper
from app.services.character_service import CharacterService
from app.services.bedmage_service import BedmageService


def register_services(container: DIContainer) -> None:
    """
    Register all services in the container.

    Args:
        container: The dependency injection container
    """
    # Register scraper
    scraper = TibiantisScraper()
    container.register(TibiantisScraper, scraper)

    # Register services
    character_service = CharacterService(scraper=scraper)
    container.register(CharacterService, character_service)

    bedmage_service = BedmageService(character_service=character_service)
    container.register(BedmageService, bedmage_service)