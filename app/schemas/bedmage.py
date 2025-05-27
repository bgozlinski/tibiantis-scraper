from marshmallow import Schema, fields
from app.schemas.character import CharacterSchema


class BedmageSchema(Schema):
    """Schema for Bedmage model serialization/validation."""

    id = fields.Int(dump_only=True)
    character_name = fields.Str(required=True)


class BedmageRequestSchema(Schema):
    """Schema for validating bedmage creation requests."""

    character_name = fields.Str(required=True)


class BedmageResponseSchema(BedmageSchema):
    """Schema for bedmage monitors API responses."""


class BedmageWithCharacterSchema(BedmageSchema):

    character = fields.Nested(CharacterSchema)


# Schema instances
bedmage_monitor_schema = BedmageSchema()
bedmages_schema = BedmageSchema(many=True)
bedmage_request_schema = BedmageRequestSchema()
bedmage_response_schema = BedmageResponseSchema()
bedmage_with_character_schema = BedmageWithCharacterSchema()