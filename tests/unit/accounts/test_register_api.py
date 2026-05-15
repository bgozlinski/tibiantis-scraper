"""Tests for POST /api/auth/register/ endpoint."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User


@pytest.mark.django_db
def test_register_creates_user_with_valid_payload() -> None:
    """Valid payload returns 201, persists User, hashes password, never leaks it."""
    client = APIClient()
    payload = {
        "username": "yhral",
        "email": "yhral@example.com",
        "password": "KomplexHaslo!23",
    }

    response = client.post(reverse("accounts_api:register"), payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert "password" not in response.data
    assert response.data["username"] == "yhral"
    assert response.data["email"] == "yhral@example.com"

    user = User.objects.get(username="yhral")
    assert user.email == "yhral@example.com"
    assert user.check_password("KomplexHaslo!23")
    assert user.password != "KomplexHaslo!23"


@pytest.mark.django_db
def test_register_rejects_duplicate_username() -> None:
    """Second registration with the same username returns 400."""
    User.objects.create_user(
        username="yhral", email="first@example.com", password="KomplexHaslo!23"
    )
    client = APIClient()
    payload = {
        "username": "yhral",
        "email": "second@example.com",
        "password": "KomplexHaslo!23",
    }

    response = client.post(reverse("accounts_api:register"), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "username" in response.data
    assert User.objects.filter(username="yhral").count() == 1


@pytest.mark.django_db
def test_register_rejects_numeric_only_password() -> None:
    """NumericPasswordValidator rejects all-digit passwords even if long enough."""
    client = APIClient()
    payload = {
        "username": "yhral",
        "email": "yhral@example.com",
        "password": "12345678",
    }

    response = client.post(reverse("accounts_api:register"), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "password" in response.data
    assert not User.objects.filter(username="yhral").exists()


@pytest.mark.django_db
def test_register_rejects_missing_email() -> None:
    """Regression guard for #133: model `email` is `null=True, blank=True` so that
    Discord auto-create can store NULL. ModelSerializer derives field metadata
    from the model — without an explicit override the REST register endpoint
    would silently accept signups with no `email` key at all. This test pins
    `required=True` on the serializer override so REST signups stay strict
    even though the underlying model column allows NULL.
    """
    client = APIClient()
    payload = {
        "username": "yhral",
        "password": "KomplexHaslo!23",
    }  # email omitted

    response = client.post(reverse("accounts_api:register"), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "email" in response.data
    assert not User.objects.filter(username="yhral").exists()


@pytest.mark.django_db
def test_register_rejects_empty_email() -> None:
    """Sibling of the missing-email guard: empty string must also be rejected.

    Since model is now `blank=True`, ModelSerializer's auto-derived field would
    allow ''. This test pins `allow_blank=False` on the serializer override
    so registered users always have a real, non-empty address.
    """
    client = APIClient()
    payload = {
        "username": "yhral",
        "email": "",
        "password": "KomplexHaslo!23",
    }

    response = client.post(reverse("accounts_api:register"), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "email" in response.data
    assert not User.objects.filter(username="yhral").exists()


@pytest.mark.django_db
def test_register_rejects_null_email() -> None:
    """Third sibling: explicit JSON `null` must also be rejected.

    Since model is now `null=True`, ModelSerializer's auto-derived field would
    allow None. This test pins `allow_null=False` on the serializer override —
    web signups always have an email even though Discord auto-creates don't.
    """
    client = APIClient()
    payload = {
        "username": "yhral",
        "email": None,
        "password": "KomplexHaslo!23",
    }

    response = client.post(reverse("accounts_api:register"), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "email" in response.data
    assert not User.objects.filter(username="yhral").exists()
