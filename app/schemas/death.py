from marshmallow import Schema, fields


class DeathSchema(Schema):
    """Schema for Character death serialization/validation."""

    date = fields.DateTime(required=True)
    killed_by = fields.Str(required=True)
    killers = fields.List(fields.Str())


death_schema = DeathSchema()
deaths_schema = DeathSchema(many=True)