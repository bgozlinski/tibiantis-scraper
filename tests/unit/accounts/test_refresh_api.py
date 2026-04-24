"""Tests for POST /api/auth/refresh/ endpoint (simplejwt TokenRefreshView)."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User


@pytest.mark.django_db
def test_refresh_returns_new_tokens_and_rotates_refresh() -> None:
    """Valid refresh returns 200 with a NEW access and a NEW refresh token.

    SIMPLE_JWT has ROTATE_REFRESH_TOKENS=True, so the response must include a
    freshly-issued refresh token distinct from the one used in the request.
    """
    User.objects.create_user(
        username="yhral", email="yhral@example.com", password="KomplexHaslo!23"
    )
    client = APIClient()
    login = client.post(
        reverse("accounts_api:login"),
        {"username": "yhral", "password": "KomplexHaslo!23"},
        format="json",
    )
    original_refresh = login.data["refresh"]

    response = client.post(
        reverse("accounts_api:refresh"),
        {"refresh": original_refresh},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["refresh"] != original_refresh


@pytest.mark.django_db
def test_refresh_returns_401_for_invalid_token() -> None:
    """Garbage refresh token returns 401."""
    client = APIClient()

    response = client.post(
        reverse("accounts_api:refresh"),
        {"refresh": "not-a-real-jwt"},
        format="json",
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
