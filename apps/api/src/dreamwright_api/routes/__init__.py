"""API routes."""

from .projects import router as projects_router
from .story import router as story_router
from .characters import router as characters_router
from .locations import router as locations_router
from .scripts import router as scripts_router
from .images import router as images_router
from .jobs import router as jobs_router
from .assets import router as assets_router

__all__ = [
    "projects_router",
    "story_router",
    "characters_router",
    "locations_router",
    "scripts_router",
    "images_router",
    "jobs_router",
    "assets_router",
]
