"""Image generation service - centralized service for all panel/image generation."""

from pathlib import Path
from typing import Callable, Optional

from dreamwright_generators.image import ImageGenerator, PanelResult
from dreamwright_core_schemas import Chapter, Panel, Scene
from dreamwright_storage import ProjectManager
from .exceptions import DependencyError, NotFoundError


class ImageService:
    """Centralized service for panel/image generation operations.

    Handles image generation at multiple levels:
    - Chapter: Generate all panel images for a chapter
    - Scene: Generate all panel images for a specific scene
    - Panel: Generate a single panel image

    Image generation depends on:
    - Script (chapter/scene/panel definitions)
    - Character reference assets
    - Location reference assets
    """

    def __init__(self, manager: ProjectManager):
        """Initialize service with a project manager."""
        self.manager = manager

    def get_chapter(self, chapter_number: int) -> Chapter:
        """Get chapter by number.

        Raises:
            NotFoundError: If chapter not found
        """
        for ch in self.manager.project.chapters:
            if ch.number == chapter_number:
                return ch
        raise NotFoundError("Chapter", str(chapter_number))

    def get_scene(self, chapter_number: int, scene_number: int) -> Scene:
        """Get scene by chapter and scene number.

        Raises:
            NotFoundError: If chapter or scene not found
        """
        chapter = self.get_chapter(chapter_number)
        for s in chapter.scenes:
            if s.number == scene_number:
                return s
        raise NotFoundError("Scene", f"{chapter_number}/{scene_number}")

    def list_panels(
        self,
        chapter_number: int,
        scene_number: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Panel], int]:
        """List panels for a chapter or scene.

        Returns:
            Tuple of (panels, total_count)
        """
        chapter = self.get_chapter(chapter_number)

        if scene_number is not None:
            scene = self.get_scene(chapter_number, scene_number)
            panels = scene.panels
        else:
            panels = []
            for scene in chapter.scenes:
                panels.extend(scene.panels)

        total = len(panels)
        return panels[offset:offset + limit], total

    def validate_dependencies(
        self,
        chapter_number: int,
        scene_number: Optional[int] = None,
    ) -> list[dict]:
        """Validate panel generation dependencies.

        Returns:
            List of missing dependencies (empty if all met)
        """
        missing = []

        # Get chapter
        try:
            chapter = self.get_chapter(chapter_number)
        except NotFoundError:
            missing.append({
                "type": "chapter",
                "chapter_number": chapter_number,
                "message": f"Chapter {chapter_number} not found",
                "resolution": f"Generate chapter {chapter_number} first",
            })
            return missing

        if not chapter.scenes:
            missing.append({
                "type": "scenes",
                "chapter_number": chapter_number,
                "message": f"Chapter {chapter_number} has no scenes",
                "resolution": "Regenerate chapter",
            })
            return missing

        # Determine scenes to check
        if scene_number is not None:
            try:
                scenes = [self.get_scene(chapter_number, scene_number)]
            except NotFoundError:
                missing.append({
                    "type": "scene",
                    "scene_number": scene_number,
                    "message": f"Scene {scene_number} not found in Chapter {chapter_number}",
                    "resolution": "Check scene number",
                })
                return missing
        else:
            scenes = chapter.scenes

        # Check previous chapter exists (for chapter N > 1)
        if chapter_number > 1:
            try:
                self.get_chapter(chapter_number - 1)
            except NotFoundError:
                missing.append({
                    "type": "previous_chapter",
                    "chapter_number": chapter_number - 1,
                    "message": f"Chapter {chapter_number - 1} must be generated first",
                    "resolution": f"Generate chapter {chapter_number - 1} first",
                })

        # Collect required assets
        characters_dict = {c.id: c for c in self.manager.project.characters}
        locations_dict = {l.id: l for l in self.manager.project.locations}

        required_char_ids = set()
        required_loc_ids = set()

        for scene in scenes:
            if scene.location_id:
                required_loc_ids.add(scene.location_id)
            for panel in scene.panels:
                for pc in panel.characters:
                    required_char_ids.add(pc.character_id)

        # Check character assets
        for char_id in required_char_ids:
            char = characters_dict.get(char_id)
            if not char:
                missing.append({
                    "type": "character",
                    "character_id": char_id,
                    "message": f"Character '{char_id}' not found in project",
                    "resolution": "Check character IDs in scene",
                })
                continue

            if not char.assets.portrait:
                missing.append({
                    "type": "character_asset",
                    "character_id": char_id,
                    "character_name": char.name,
                    "message": f"No portrait asset for {char.name}",
                    "resolution": f"Generate portrait asset for character '{char.name}'",
                })
                continue

            portrait_path = self.manager.storage.get_absolute_asset_path(char.assets.portrait)
            if not portrait_path.exists():
                missing.append({
                    "type": "character_asset",
                    "character_id": char_id,
                    "character_name": char.name,
                    "message": f"Portrait file missing for {char.name}",
                    "resolution": f"Regenerate portrait asset for character '{char.name}'",
                })

        # Check location assets
        for loc_id in required_loc_ids:
            loc = locations_dict.get(loc_id)
            if not loc:
                missing.append({
                    "type": "location",
                    "location_id": loc_id,
                    "message": f"Location '{loc_id}' not found in project",
                    "resolution": "Check location IDs in scene",
                })
                continue

            if not loc.assets.reference:
                missing.append({
                    "type": "location_asset",
                    "location_id": loc_id,
                    "location_name": loc.name,
                    "message": f"No reference asset for {loc.name}",
                    "resolution": f"Generate reference asset for location '{loc.name}'",
                })
                continue

            ref_path = self.manager.storage.get_absolute_asset_path(loc.assets.reference)
            if not ref_path.exists():
                missing.append({
                    "type": "location_asset",
                    "location_id": loc_id,
                    "location_name": loc.name,
                    "message": f"Reference file missing for {loc.name}",
                    "resolution": f"Regenerate reference asset for location '{loc.name}'",
                })

        return missing

    def _build_references(self) -> tuple[dict[str, Path], dict[str, Path]]:
        """Build character and location reference path dicts.

        For characters, prefers three-view sheet over portrait for better
        consistency across different poses and angles.

        Returns:
            Tuple of (character_refs, location_refs)
        """
        character_refs = {}
        for char in self.manager.project.characters:
            # Prefer character sheet (three-view) over portrait for panel generation
            ref_path = None
            if char.assets.three_view.get("sheet"):
                sheet_path = self.manager.storage.get_absolute_asset_path(
                    char.assets.three_view["sheet"]
                )
                if sheet_path.exists():
                    ref_path = sheet_path

            # Fall back to portrait if no sheet available
            if ref_path is None and char.assets.portrait:
                portrait_path = self.manager.storage.get_absolute_asset_path(char.assets.portrait)
                if portrait_path.exists():
                    ref_path = portrait_path

            if ref_path:
                character_refs[char.id] = ref_path

        location_refs = {}
        for loc in self.manager.project.locations:
            if loc.assets.reference:
                ref_path = self.manager.storage.get_absolute_asset_path(loc.assets.reference)
                if ref_path.exists():
                    location_refs[loc.id] = ref_path

        return character_refs, location_refs

    async def generate_panels(
        self,
        chapter_number: int,
        scene_number: Optional[int] = None,
        style: str = "webtoon",
        overwrite: bool = False,
        on_panel_start: Optional[Callable[[Panel], None]] = None,
        on_panel_complete: Optional[Callable[[PanelResult], None]] = None,
        on_scene_start: Optional[Callable[[Scene], None]] = None,
    ) -> dict:
        """Generate panels for a chapter or scene.

        Args:
            chapter_number: Chapter number
            scene_number: Optional scene number (generates all if None)
            style: Art style
            overwrite: Whether to overwrite existing
            on_panel_start: Callback when panel generation starts
            on_panel_complete: Callback when panel generation completes
            on_scene_start: Callback when scene generation starts

        Returns:
            Generation result dict

        Raises:
            DependencyError: If dependencies not met
        """
        # Validate dependencies
        missing = self.validate_dependencies(chapter_number, scene_number)
        if missing:
            raise DependencyError(
                f"Cannot generate panels for chapter {chapter_number}: dependencies not met",
                missing,
            )

        chapter = self.get_chapter(chapter_number)
        characters_dict = {c.id: c for c in self.manager.project.characters}
        locations_dict = {l.id: l for l in self.manager.project.locations}
        character_refs, location_refs = self._build_references()

        generator = ImageGenerator()

        if scene_number is not None:
            # Generate single scene
            scene = self.get_scene(chapter_number, scene_number)

            if on_scene_start:
                on_scene_start(scene)

            result = await generator.generate_scene_panels(
                scene=scene,
                chapter_number=chapter_number,
                characters=characters_dict,
                locations=locations_dict,
                character_references=character_refs,
                location_references=location_refs,
                output_dir=self.manager.storage.assets_path,
                style=style,
                overwrite=overwrite,
                on_panel_start=on_panel_start,
                on_panel_complete=on_panel_complete,
            )

            self.manager.save()

            return {
                "chapter_number": chapter_number,
                "scene_number": scene_number,
                "generated_count": result.generated_count,
                "skipped_count": result.skipped_count,
                "error_count": result.error_count,
            }
        else:
            # Generate full chapter
            # Find previous chapter's last panel for cross-chapter continuity
            prev_chapter_last_panel = None
            if chapter_number > 1:
                try:
                    prev_chapter = self.get_chapter(chapter_number - 1)
                    if prev_chapter.scenes:
                        last_scene = prev_chapter.scenes[-1]
                        if last_scene.panels:
                            last_panel = last_scene.panels[-1]
                            if last_panel.image_path:
                                prev_path = self.manager.storage.get_absolute_asset_path(
                                    last_panel.image_path
                                )
                                if prev_path.exists():
                                    prev_chapter_last_panel = prev_path
                except NotFoundError:
                    pass

            result = await generator.generate_chapter_panels(
                chapter=chapter,
                characters=characters_dict,
                locations=locations_dict,
                character_references=character_refs,
                location_references=location_refs,
                output_dir=self.manager.storage.assets_path,
                style=style,
                overwrite=overwrite,
                previous_chapter_last_panel=prev_chapter_last_panel,
                on_scene_start=on_scene_start,
                on_panel_start=on_panel_start,
                on_panel_complete=on_panel_complete,
            )

            self.manager.save()

            return {
                "chapter_number": chapter_number,
                "generated_count": result.generated_count,
                "skipped_count": result.skipped_count,
                "error_count": result.error_count,
                "output_dir": f"assets/panels/chapter-{chapter_number}/",
            }

    def get_panel(self, chapter_number: int, scene_number: int, panel_number: int) -> Panel:
        """Get a specific panel.

        Raises:
            NotFoundError: If chapter, scene, or panel not found
        """
        scene = self.get_scene(chapter_number, scene_number)
        for p in scene.panels:
            if p.number == panel_number:
                return p
        raise NotFoundError("Panel", f"{chapter_number}/{scene_number}/{panel_number}")

    async def generate_single_panel(
        self,
        chapter_number: int,
        scene_number: int,
        panel_number: int,
        style: str = "webtoon",
        overwrite: bool = False,
        on_panel_start: Optional[Callable[[Panel], None]] = None,
        on_panel_complete: Optional[Callable[[PanelResult], None]] = None,
    ) -> PanelResult:
        """Generate a single panel image.

        Args:
            chapter_number: Chapter number
            scene_number: Scene number
            panel_number: Panel number
            style: Art style
            overwrite: Whether to overwrite existing
            on_panel_start: Callback when panel generation starts
            on_panel_complete: Callback when panel generation completes

        Returns:
            PanelResult with generation status

        Raises:
            NotFoundError: If chapter, scene, or panel not found
            DependencyError: If dependencies not met
        """
        # Get the panel
        chapter = self.get_chapter(chapter_number)
        scene = self.get_scene(chapter_number, scene_number)
        panel = self.get_panel(chapter_number, scene_number, panel_number)

        # Build references
        characters_dict = {c.id: c for c in self.manager.project.characters}
        locations_dict = {l.id: l for l in self.manager.project.locations}
        character_refs, location_refs = self._build_references()

        # Get location for this scene
        location = locations_dict.get(scene.location_id)
        location_ref = location_refs.get(scene.location_id)

        # Get previous panel image for continuity
        previous_panel_image = None
        if panel_number > 1:
            # Get previous panel in same scene
            for p in scene.panels:
                if p.number == panel_number - 1 and p.image_path:
                    prev_path = self.manager.storage.get_absolute_asset_path(p.image_path)
                    if prev_path.exists():
                        previous_panel_image = prev_path
                    break
        elif scene_number > 1:
            # Get last panel from previous scene
            prev_scene = None
            for s in chapter.scenes:
                if s.number == scene_number - 1:
                    prev_scene = s
                    break
            if prev_scene and prev_scene.panels:
                last_panel = prev_scene.panels[-1]
                if last_panel.image_path:
                    prev_path = self.manager.storage.get_absolute_asset_path(last_panel.image_path)
                    if prev_path.exists():
                        previous_panel_image = prev_path

        # Check if panel already exists
        output_dir = self.manager.storage.assets_path
        panel_path = output_dir / f"panels/chapter-{chapter_number}/scene-{scene_number}/panel-{panel_number}.png"
        if panel_path.exists() and not overwrite:
            result = PanelResult(
                panel=panel,
                image_data=None,
                metadata=None,
                error=None,
                skipped=True,
            )
            if on_panel_complete:
                on_panel_complete(result)
            return result

        if on_panel_start:
            on_panel_start(panel)

        generator = ImageGenerator()

        try:
            # Get characters for this panel
            panel_characters = {
                pc.character_id: characters_dict[pc.character_id]
                for pc in panel.characters
                if pc.character_id in characters_dict
            }

            # Generate the panel
            image_data, metadata = await generator.generate_panel(
                panel=panel,
                characters=panel_characters,
                location=location,
                time_of_day=scene.time_of_day,
                character_references=character_refs,
                location_reference=location_ref,
                previous_panel_image=previous_panel_image,
                style=style,
                scene_number=scene_number,
                chapter_number=chapter_number,
                overwrite_cache=overwrite,
            )

            # Save the panel
            panel_rel_path = f"panels/chapter-{chapter_number}/scene-{scene_number}"
            saved_path = self.manager.save_asset(
                panel_rel_path,
                f"panel-{panel_number}.png",
                image_data,
                metadata=metadata,
            )
            panel.image_path = saved_path

            self.manager.save()

            result = PanelResult(
                panel=panel,
                image_data=image_data,
                metadata=metadata,
                error=None,
                skipped=False,
            )
        except Exception as e:
            result = PanelResult(
                panel=panel,
                image_data=None,
                metadata=None,
                error=str(e),
                skipped=False,
            )

        if on_panel_complete:
            on_panel_complete(result)

        return result


# Backwards compatibility alias
PanelService = ImageService
