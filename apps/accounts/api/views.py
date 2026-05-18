"""REST views for the accounts app.

Per the project rule that REST is auth-only, this module exposes just user
registration. Login, refresh and logout are handled by ``rest_framework_simplejwt``
views wired in :mod:`apps.accounts.api.urls`.
"""

from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from apps.accounts.api.serializers import RegisterSerializer
from apps.accounts.models import User


class RegisterView(CreateAPIView[User]):
    """Anonymous endpoint that creates a new :class:`User`.

    Accepts ``username``, ``email`` and ``password`` and runs Django's password
    validators through :class:`RegisterSerializer`.
    """

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
