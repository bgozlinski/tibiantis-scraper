from typing import Dict, Any, Optional, TypeVar, cast, Type

T = TypeVar('T')


class DIContainer:
    """
    Simple dependency injection container.

    This container allows registering and retrieving services by type or name.
    """
    def __init__(self) -> None:
        self._services: Dict[str, Any] = {}

    def register(self,
                 service_type: Type[T],
                 instance: T,
                 name: Optional[str] = None
                 ) -> None:
        """
        Register a service in the container.

        Args:
            service_type: The type of the service
            instance: The service instance
            name: Optional name for the service (for multiple instances of same type)
        """
        key = self._get_key(service_type, name)
        self._services[key] = instance

    def get(self, service_type: Type[T], name: Optional[str] = None) -> T:
        """
        Get a service from the container.

        Args:
            service_type: The type of the service to retrieve
            name: Optional name for the service

        Returns:
            The service instance

        Raises:
            KeyError: If the service is not registered
        """
        key = self._get_key(service_type, name)
        if key not in self._services:
            raise KeyError(f"Service {key} not registered")
        return cast(T, self._services[key])

    def _get_key(self, service_type: Type, name: Optional[str] = None) -> str:
        """
        Generate a key for the service.

        Args:
            service_type: The type of the service
            name: Optional name for the service

        Returns:
            The key for the service
        """
        type_name = service_type.__name__
        return f"{type_name}_{name}" if name else type_name
