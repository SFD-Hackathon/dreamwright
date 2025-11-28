"""DreamWright Services - Shared business logic for CLI and API.

Primary Services:
- ScriptService: All script/storyboard generation (chapter, scene, panel scripts)
- ImageService: All panel image generation (chapter, scene, panel images)
- CharacterService: Character management and asset generation
- LocationService: Location management and asset generation
- StoryService: Story expansion from prompts
- ProjectService: Project management
- JobService: Background job management

Deprecated (use alternatives):
- ChapterService: Use ScriptService instead
- PanelService: Use ImageService instead
"""

from .project import ProjectService
from .story import StoryService
from .character import CharacterService
from .location import LocationService
from .script import ScriptService
from .image import ImageService, PanelService  # PanelService is alias for backwards compat
from .job import JobService, Job, JobStatus

# Backwards compatibility - ChapterService functionality merged into ScriptService
# Import will still work but users should migrate to ScriptService
from .chapter import ChapterService

__all__ = [
    # Primary services
    "ProjectService",
    "StoryService",
    "CharacterService",
    "LocationService",
    "ScriptService",
    "ImageService",
    "JobService",
    "Job",
    "JobStatus",
    # Deprecated aliases (for backwards compatibility)
    "ChapterService",  # Use ScriptService
    "PanelService",    # Use ImageService
]
