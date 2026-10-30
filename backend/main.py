"""ASGI entry point: `uvicorn backend.main:create --factory` (real wiring from environment variables)."""
from backend.api.app import create_app
from backend.services import services_from_env


def create():
    return create_app(services_from_env(), start_background=True, remediate=True)
