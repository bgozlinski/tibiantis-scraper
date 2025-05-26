# Scheduled Tasks in Tibiantis Scraper

This document explains the implementation of scheduled tasks in the Tibiantis Scraper application.

## Overview

The application now includes a scheduler that automatically runs certain tasks at specified intervals. This eliminates the need for manual API calls or external scheduling tools.

## Implemented Scheduled Tasks

### Add Online Characters

- **Endpoint**: `/api/v1/characters/online/add`
- **Function**: `add_new_online_characters()`
- **Schedule**: Every 15 minutes
- **Description**: This task automatically fetches the list of characters currently online on the Tibiantis server and adds any new characters (not already in the database) to the database.

## Implementation Details

The scheduler is implemented using Flask-APScheduler, a Flask extension for the APScheduler library. The implementation can be found in `app/utils/scheduler.py`.

Key components:
1. A scheduler instance is initialized at the module level in `app/utils/scheduler.py`
2. A dedicated function `scheduled_add_online_characters()` is created to be called by the scheduler
3. An `init_scheduler(app)` function is provided to configure and start the scheduler with the Flask application
4. The scheduler is initialized and started when the Flask application starts in `app/main.py`
5. The task is scheduled to run every 15 minutes

## Logs

The scheduler logs its activity to the application logs. You can monitor these logs to verify that the scheduled task is running correctly:

- When the scheduler starts: `"Scheduler started: add_online_characters will run every 15 minutes"`
- When the task runs: `"Running scheduled task: Adding online characters"`
- When the task completes: `"Scheduled task completed: {results}"`
- If there's an error: `"Error in scheduled task: {error_message}"`

## Testing

To test that the scheduler is working correctly:

1. Start the Flask application
2. Check the logs to verify that the scheduler has started
3. Wait for 15 minutes or restart the application to trigger the first run
4. Check the logs to verify that the task has run and completed successfully

## Manual Execution

The scheduled task does not replace the API endpoint. You can still manually trigger the task by making a POST request to `/api/v1/characters/online/add`.

## Dependencies

The scheduler requires the Flask-APScheduler package, which has been added to the requirements.txt file. Make sure to install the updated dependencies:

```
pip install -r requirements.txt
```

## Customization

If you need to change the schedule or add more scheduled tasks, you can modify the scheduler configuration in `app/utils/scheduler.py`. To add a new scheduled task:

1. Define a new function in `app/utils/scheduler.py` that will be called by the scheduler
2. Add a new job in the `init_scheduler(app)` function using `scheduler.add_job()`
