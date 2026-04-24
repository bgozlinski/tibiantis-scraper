from django.urls import path
from apps.accounts.api.views import RegisterView
from rest_framework_simplejwt.views import (
    TokenObtainPairView as LoginView,
    TokenRefreshView as RefreshView,
    TokenBlacklistView as LogoutView,
)

app_name = "accounts_api"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshView.as_view(), name="refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
