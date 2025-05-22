class Config:
    DEBUG = False
    TESTING = False

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///./database.db"


class ProductionConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///./database.db"


