"""Serializers for the REST registration endpoint."""

from typing import Any

from rest_framework import serializers
from django.contrib.auth.password_validation import (
    validate_password as django_validate_password,
)
from django.core.exceptions import ValidationError as DjangoValidationError
from apps.accounts.models import User


class RegisterSerializer(serializers.ModelSerializer[User]):
    """Serializer that creates a new :class:`User` from the REST register call.

    Enforces a non-empty unique ``email`` (the model column is nullable to
    accommodate Discord-only users, but the REST flow always requires it) and
    runs every Django password validator before accepting the credentials.
    """

    email = serializers.EmailField(required=True, allow_null=False, allow_blank=False)

    class Meta:
        model = User
        fields = [
            "username",
            "password",
            "email",
        ]
        extra_kwargs = {"password": {"write_only": True}}

    def validate_password(self, value: str) -> str:
        """Run Django's configured password validators on ``value``.

        Re-raises any :class:`~django.core.exceptions.ValidationError` from
        Django as a DRF :class:`~rest_framework.serializers.ValidationError`
        so the API responds with structured field errors instead of a 500.
        """
        try:
            django_validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return value

    def create(self, validated_data: dict[str, Any]) -> User:
        """Create the user through ``create_user`` so the password gets hashed."""
        return User.objects.create_user(**validated_data)
