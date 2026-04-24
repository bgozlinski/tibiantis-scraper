from typing import Any

from rest_framework import serializers
from django.contrib.auth.password_validation import (
    validate_password as django_validate_password,
)
from django.core.exceptions import ValidationError as DjangoValidationError
from apps.accounts.models import User


class RegisterSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = [
            "username",
            "password",
            "email",
        ]
        extra_kwargs = {"password": {"write_only": True}}

    def validate_password(self, value: str) -> str:
        try:
            django_validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return value

    def create(self, validated_data: dict[str, Any]) -> User:
        return User.objects.create_user(**validated_data)
