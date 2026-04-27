from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from apps.accounts.api.serializers import RegisterSerializer
from apps.accounts.models import User


class RegisterView(CreateAPIView[User]):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
