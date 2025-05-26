
# Tibiantis Scraper

A Flask-based API for scraping and storing character data from the Tibiantis server. This application provides endpoints to retrieve character information, track online players, and maintain a database of character statistics.

## Features

- **Character Information**: Retrieve detailed information about characters
- **Death History**: Access character death records
- **Online Players**: Get a list of currently online players
- **Automated Data Collection**: Scheduled tasks to periodically collect and update data
- **RESTful API**: Well-structured API endpoints for easy integration

## Installation

### Prerequisites

- Python 3.8+
- pip

### Setup

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/tibiantis-scraper.git
   cd tibiantis-scraper
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root with the following content:
   ```
   FLASK_ENV=development
   DATABASE_URL=sqlite:///./database.db
   ```

5. Initialize the database:
   ```
   alembic upgrade head
   ```

## Usage

### Running the Application

Start the Flask application:
```
python run.py
```

The API will be available at `http://127.0.0.1:5000`.

## API Endpoints

### Character Endpoints

- **GET /api/v1/characters/{name}** - Get basic character information
- **GET /api/v1/characters/{name}/full** - Get detailed character information
- **GET /api/v1/characters/{name}/deaths** - Get character death history
- **POST /api/v1/characters/{name}** - Add a character to the database
- **GET /api/v1/characters/{name}/login-time** - Get time since last login

### Online Characters Endpoints

- **GET /api/v1/characters/online** - Get list of currently online characters
- **POST /api/v1/characters/online/add** - Add all currently online characters to the database

### Update Endpoints

- **POST /api/v1/characters/update-all** - Update all characters in the database

## Scheduled Tasks

The application includes a scheduler that automatically runs certain tasks at specified intervals:

### Add Online Characters

- **Schedule**: Every 15 minutes
- **Description**: Automatically fetches the list of characters currently online on the Tibiantis server and adds any new characters to the database.

For more details about the scheduler implementation, see [SCHEDULER_README.md](SCHEDULER_README.md).

## Project Structure

```
tibiantis-scraper/
├── alembic/                  # Database migration scripts
├── app/                      # Main application package
│   ├── db/                   # Database related code
│   │   ├── models/           # SQLAlchemy models
│   │   └── session.py        # Database session management
│   ├── routes/               # API route definitions
│   ├── schemas/              # Marshmallow schemas for serialization
│   ├── scraper/              # Web scraping functionality
│   ├── services/             # Business logic
│   ├── utils/                # Utility functions
│   ├── config.py             # Application configuration
│   └── main.py               # Flask application factory
├── tests/                    # Test cases
├── .env                      # Environment variables
├── alembic.ini               # Alembic configuration
├── requirements.txt          # Project dependencies
├── run.py                    # Application entry point
└── SCHEDULER_README.md       # Scheduler documentation
```

## Development

### Running Tests

```
pytest
```

For test coverage:
```
pytest --cov=app tests/
```

### Database Migrations

To create a new migration after model changes:
```
alembic revision --autogenerate -m "Description of changes"
```

To apply migrations:
```
alembic upgrade head
```

## Dependencies

- **Flask**: Web framework
- **SQLAlchemy**: ORM for database operations
- **BeautifulSoup4**: HTML parsing for web scraping
- **Requests**: HTTP library for making requests
- **Flask-APScheduler**: Task scheduling
- **Alembic**: Database migrations
- **python-dotenv**: Environment variable management

For a complete list of dependencies, see [requirements.txt](requirements.txt).

## License

This project is licensed under the MIT License—see the [LICENSE](LICENSE) file for details.
## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request