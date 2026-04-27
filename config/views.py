from typing import Any
from django.http import HttpRequest, HttpResponseBase
from asgiref.sync import sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from strawberry.django.views import AsyncGraphQLView
from rest_framework.request import Request as DRFRequest


class JWTAsyncGraphQLView(AsyncGraphQLView):
    async def dispatch(  # type: ignore[override]
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        _authenticator = JWTAuthentication()
        try:
            auth_result: tuple[Any, Any] | None = await sync_to_async(
                _authenticator.authenticate  # type: ignore[arg-type]
            )(DRFRequest(request))
            if auth_result is not None:
                user, _ = auth_result
                request.user = user
            else:
                request.user = AnonymousUser()

        except AuthenticationFailed:
            request.user = AnonymousUser()

        return await super().dispatch(request, *args, **kwargs)
