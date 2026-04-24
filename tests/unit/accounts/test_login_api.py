"""Tests for POST /api/auth/login/ endpoint (simplejwt TokenObtainPairView)."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User


@pytest.mark.django_db
def test_login_returns_access_and_refresh_for_valid_credentials() -> None:
    """Valid username + password returns 200 with {access, refresh} JWT pair."""
    User.objects.create_user(
        username="yhral", email="yhral@example.com", password="KomplexHaslo!23"
    )
    client = APIClient()
    payload = {"username": "yhral", "password": "KomplexHaslo!23"}

    response = client.post(reverse("accounts_api:login"), payload, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data
    assert "refresh" in response.data
    assert isinstance(response.data["access"], str)
    assert isinstance(response.data["refresh"], str)


@pytest.mark.django_db
def test_login_returns_401_for_wrong_password() -> None:
    """Wrong password returns 401, no tokens leak."""
    User.objects.create_user(
        username="yhral", email="yhral@example.com", password="KomplexHaslo!23"
    )
    client = APIClient()
    payload = {"username": "yhral", "password": "wrong-password"}

    response = client.post(reverse("accounts_api:login"), payload, format="json")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "access" not in response.data
    assert "refresh" not in response.data
