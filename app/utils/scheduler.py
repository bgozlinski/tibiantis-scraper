"""
Scheduler module for the Tibiantis Scraper application.

This module contains the scheduler configuration and scheduled tasks.
"""
import logging
import os

from flask_apscheduler import APScheduler
from app.services.character_service import CharacterService

logger = logging.getLogger(__name__)

# Initialize scheduler
scheduler = APScheduler()

# Function to be scheduled
def scheduled_add_online_characters():
    """
    Scheduled task to add online characters to the database every 15 minutes.
    """
    logger.info("Running scheduled task: Adding online characters")
    try:
        character_service = CharacterService()
        results = character_service.add_new_online_characters()
        logger.info(f"Scheduled task completed: {results}")
    except Exception as e:
        logger.error(f"Error in scheduled task: {str(e)}")

def init_scheduler(app):
    """
    Initialize and start the scheduler with the Flask application.
    
    Args:
        app: Flask application instance
    """
    # Configure scheduler
    app.config['SCHEDULER_API_ENABLED'] = True
    
    # Initialize scheduler with app
    scheduler.init_app(app)

    # Only start the scheduler in the main process when in debug mode
    if not app.debug or (app.debug and not os.environ.get('WERKZEUG_RUN_MAIN') == 'true'):
        # Define the minutes variable before using it
        minutes_interval = 2
        # Add job to run every 15 minutes
        scheduler.add_job(
            id='add_online_characters_job',
            func=scheduled_add_online_characters,
            trigger='interval',
            minutes=minutes_interval
        )
    
        # Start scheduler
        scheduler.start()
        logger.info(f"Scheduler started: add_online_characters will run every {minutes_interval} minutes")