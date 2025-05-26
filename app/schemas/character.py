from marshmallow import Schema, fields
from app.schemas.death import DeathSchema


class CharacterSchema(Schema):
    """Schema for Character model serialization/validation."""

    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    sex = fields.Str(allow_none=True)
    vocation = fields.Str(allow_none=True)
    level = fields.Int(allow_none=True)
    world = fields.Str(allow_none=True)
    residence = fields.Str(allow_none=True)
    house = fields.Str(allow_none=True)
    guild_membership = fields.Str(allow_none=True)
    last_login = fields.DateTime(allow_none=True)
    comment = fields.Str(allow_none=True)
    account_status = fields.Str(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class CharacterRequestSchema(Schema):
    """Schema for validating character creation requests."""

    name = fields.Str(required=True)


class CharacterResponseSchema(CharacterSchema):
    """Schema for character API responses."""

    # Inherits all fields from CharacterSchema
    # Can add additional response-specific fields here


class CharacterWithDeathsSchema(CharacterSchema):
    """Schema for character data with death history."""

    deaths = fields.List(fields.Nested(DeathSchema))


class CharacterLoginTimeSchema(Schema):
    """Schema for character login time information."""

    name = fields.Str(required=True)
    minutes_since_last_login = fields.Int()
    can_login = fields.Bool()

# Schema instances
character_schema = CharacterSchema()
characters_schema = CharacterSchema(many=True)
character_request_schema = CharacterRequestSchema()
character_response_schema = CharacterResponseSchema()
character_with_deaths_schema = CharacterWithDeathsSchema()
character_login_time_schema = CharacterLoginTimeSchema()