"""Tests for POST /api/auth/logout/ endpoint (simplejwt TokenBlacklistView)."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User


@pytest.mark.django_db
def test_logout_blacklists_refresh_token() -> None:
    """Logout returns 200 and blacklisted refresh can no longer be exchanged.

    Flow: login → logout with refresh → same refresh to /refresh/ must 401.
    Proves BLACKLIST_AFTER_ROTATION wiring plus token_blacklist app migrations
    are both in place.
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
    refresh_token = login.data["refresh"]

    logout_response = client.post(
        reverse("accounts_api:logout"),
        {"refresh": refresh_token},
        format="json",
    )

    assert logout_response.status_code == status.HTTP_200_OK

    reuse_response = client.post(
        reverse("accounts_api:refresh"),
        {"refresh": refresh_token},
        format="json",
    )
    assert reuse_response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_logout_returns_401_for_invalid_token() -> None:
    """Garbage refresh token returns 401 — cannot blacklist what isn't a token."""
    client = APIClient()

    response = client.post(
        reverse("accounts_api:logout"),
        {"refresh": "not-a-real-jwt"},
        format="json",
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
