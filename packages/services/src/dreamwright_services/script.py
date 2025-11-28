"""Script generation service - centralized service for all script/storyboard generation."""

from typing import Callable, Optional

from dreamwright_generators.script import ScriptGenerator
from dreamwright_core_schemas import Chapter, ChapterStatus, Scene, Panel, StoryBeat
from dreamwright_storage import ProjectManager
from .exceptions import DependencyError, NotFoundError, ValidationError

# Callback type aliases for interactive mode
OnChapterStart = Callable[[int, StoryBeat], None]
OnChapterComplete = Callable[[Chapter], None]


class ScriptService:
    """Centralized service for script/storyboard generation operations.

    Handles generation and regeneration of:
    - Chapters (full chapter from story beat)
    - Scenes (regenerate specific scene within chapter)
    - Panels (regenerate specific panel within scene)

    All methods support optional feedback for guided regeneration.
    """

    def __init__(self, manager: ProjectManager):
        """Initialize service with a project manager."""
        self.manager = manager
        self._generator: Optional[ScriptGenerator] = None

    @property
    def generator(self) -> ScriptGenerator:
        """Lazy-load the script generator."""
        if self._generator is None:
            self._generator = ScriptGenerator()
        return self._generator

    def _validate_story(self) -> None:
        """Validate that a story exists."""
        if not self.manager.project.story:
            raise ValidationError("No story expanded yet. Run 'dreamwright expand' first.")

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
        """Get a specific scene from a chapter.

        Raises:
            NotFoundError: If chapter or scene not found
        """
        chapter = self.get_chapter(chapter_number)
        for scene in chapter.scenes:
            if scene.number == scene_number:
                return scene
        raise NotFoundError("Scene", f"{chapter_number}/{scene_number}")

    def get_panel(self, chapter_number: int, scene_number: int, panel_number: int) -> Panel:
        """Get a specific panel from a scene.

        Raises:
            NotFoundError: If chapter, scene, or panel not found
        """
        scene = self.get_scene(chapter_number, scene_number)
        for panel in scene.panels:
            if panel.number == panel_number:
                return panel
        raise NotFoundError("Panel", f"{chapter_number}/{scene_number}/{panel_number}")

    def get_beat(self, beat_number: int) -> StoryBeat:
        """Get story beat by number.

        Raises:
            ValidationError: If beat number invalid or no story
        """
        self._validate_story()
        story = self.manager.project.story
        if not story.story_beats:
            raise ValidationError("No story beats found")

        if beat_number < 1 or beat_number > len(story.story_beats):
            raise ValidationError(
                f"Invalid beat number. Must be 1-{len(story.story_beats)}",
                field="beat_number",
            )
        return story.story_beats[beat_number - 1]

    def validate_chapter_dependencies(self, beat_number: int) -> list[dict]:
        """Validate chapter generation dependencies.

        Returns:
            List of missing dependencies (empty if all met)
        """
        missing = []
        if beat_number > 1:
            existing_numbers = {c.number for c in self.manager.project.chapters}
            if beat_number - 1 not in existing_numbers:
                missing.append({
                    "type": "previous_chapter",
                    "chapter_number": beat_number - 1,
                    "message": f"Chapter {beat_number - 1} must be generated first",
                    "resolution": f"Generate chapter {beat_number - 1} first for story continuity",
                })
        return missing

    async def generate_chapter(
        self,
        beat_number: int,
        panels_per_scene: int = 6,
        feedback: Optional[str] = None,
    ) -> Chapter:
        """Generate a chapter from a story beat.

        Args:
            beat_number: Story beat number (1-indexed)
            panels_per_scene: Target panels per scene
            feedback: Optional feedback/instructions to guide generation

        Returns:
            Generated chapter

        Raises:
            DependencyError: If dependencies not met
            ValidationError: If beat number invalid
        """
        self._validate_story()
        beat = self.get_beat(beat_number)

        # Validate dependencies
        missing = self.validate_chapter_dependencies(beat_number)
        if missing:
            raise DependencyError(
                f"Cannot generate chapter {beat_number}: dependencies not met",
                missing,
            )

        story = self.manager.project.story
        existing_chapters = sorted(self.manager.project.chapters, key=lambda c: c.number)

        # Build prompt with optional feedback
        prompt = self.generator.build_chapter_prompt(
            story=story,
            beat=beat,
            chapter_number=beat_number,
            characters=self.manager.project.characters,
            locations=self.manager.project.locations,
            previous_chapters=existing_chapters,
            panels_per_scene=panels_per_scene,
        )

        if feedback:
            prompt += f"\n\n## ADDITIONAL INSTRUCTIONS\n{feedback}"

        # Generate
        chapter = await self.generator.generate_chapter_from_prompt(
            prompt=prompt,
            characters=self.manager.project.characters,
            locations=self.manager.project.locations,
        )

        chapter.status = ChapterStatus.COMPLETED
        self._save_chapter(chapter)
        return chapter

    async def regenerate_scene(
        self,
        chapter_number: int,
        scene_number: int,
        panels_per_scene: int = 6,
        feedback: Optional[str] = None,
    ) -> Scene:
        """Regenerate a specific scene within a chapter.

        Args:
            chapter_number: Chapter number containing the scene
            scene_number: Scene number to regenerate
            panels_per_scene: Target panels for the scene
            feedback: Optional feedback/instructions to guide regeneration
                e.g., "Include both Kai and Madam Zhu in interaction panels"

        Returns:
            Regenerated Scene

        Raises:
            NotFoundError: If chapter not found
            ValidationError: If no story expanded
        """
        self._validate_story()
        chapter = self.get_chapter(chapter_number)

        # Build prompt with optional feedback
        prompt = self.generator.build_scene_prompt(
            chapter=chapter,
            scene_number=scene_number,
            story=self.manager.project.story,
            characters=self.manager.project.characters,
            locations=self.manager.project.locations,
            panels_per_scene=panels_per_scene,
        )

        if feedback:
            prompt += f"\n\n## SPECIFIC FEEDBACK TO ADDRESS\n{feedback}"

        # Generate using the modified prompt
        from dreamwright_generators.script import SceneResponse, CHAPTER_GENERATION_PROMPT
        response = await self.generator.client.generate_structured(
            prompt=prompt,
            response_schema=SceneResponse,
            system_instruction=CHAPTER_GENERATION_PROMPT,
            temperature=0.8,
        )

        new_scene = self.generator._convert_scene(
            response,
            scene_number,
            self.manager.project.characters,
            self.manager.project.locations,
            chapter_number=chapter_number
        )

        # Replace the scene in the chapter
        for i, scene in enumerate(chapter.scenes):
            if scene.number == scene_number:
                chapter.scenes[i] = new_scene
                break
        else:
            chapter.scenes.append(new_scene)
            chapter.scenes.sort(key=lambda s: s.number)

        self.manager.save()
        return new_scene

    async def regenerate_panel(
        self,
        chapter_number: int,
        scene_number: int,
        panel_number: int,
        feedback: Optional[str] = None,
    ) -> Panel:
        """Regenerate a specific panel within a scene.

        Args:
            chapter_number: Chapter number containing the panel
            scene_number: Scene number containing the panel
            panel_number: Panel number to regenerate
            feedback: Optional feedback/instructions to guide regeneration
                e.g., "Include both characters - Kai receiving and Madam Zhu giving the bag"

        Returns:
            Regenerated Panel

        Raises:
            NotFoundError: If chapter or scene not found
            ValidationError: If no story expanded
        """
        self._validate_story()
        chapter = self.get_chapter(chapter_number)
        scene = self.get_scene(chapter_number, scene_number)

        # Build prompt with optional feedback
        prompt = self.generator.build_panel_prompt(
            chapter=chapter,
            scene=scene,
            panel_number=panel_number,
            story=self.manager.project.story,
            characters=self.manager.project.characters,
            locations=self.manager.project.locations,
        )

        if feedback:
            prompt += f"\n\n## SPECIFIC FEEDBACK TO ADDRESS\n{feedback}"

        # Generate using the modified prompt
        from dreamwright_generators.script import PanelResponse, CHAPTER_GENERATION_PROMPT
        response = await self.generator.client.generate_structured(
            prompt=prompt,
            response_schema=PanelResponse,
            system_instruction=CHAPTER_GENERATION_PROMPT,
            temperature=0.8,
        )

        new_panel = self.generator._convert_panel(
            response,
            self.manager.project.characters,
            self.manager.project.locations,
            chapter_number=chapter_number,
            scene_number=scene_number,
        )

        # Preserve panel number from request (response might have different number)
        new_panel.number = panel_number
        # Also update ID to match the panel number
        new_panel.id = f"ch{chapter_number}_s{scene_number}_p{panel_number}"

        # Replace the panel in the scene
        for i, panel in enumerate(scene.panels):
            if panel.number == panel_number:
                scene.panels[i] = new_panel
                break
        else:
            scene.panels.append(new_panel)
            scene.panels.sort(key=lambda p: p.number)

        self.manager.save()
        return new_panel

    def _save_chapter(self, chapter: Chapter) -> None:
        """Save a chapter to the project."""
        existing_idx = None
        for i, c in enumerate(self.manager.project.chapters):
            if c.number == chapter.number:
                existing_idx = i
                break

        if existing_idx is not None:
            self.manager.project.chapters[existing_idx] = chapter
        else:
            self.manager.project.chapters.append(chapter)
            self.manager.project.chapters.sort(key=lambda c: c.number)

        self.manager.save()

    def get_script_status(self) -> dict:
        """Get overall script generation status.

        Returns:
            Status dict with chapters, scenes, and panels info
        """
        if not self.manager.project.story:
            return {
                "story_expanded": False,
                "total_beats": 0,
                "chapters": [],
            }

        total_beats = len(self.manager.project.story.story_beats)
        chapters_info = []

        for ch in sorted(self.manager.project.chapters, key=lambda c: c.number):
            scenes_info = []
            for scene in ch.scenes:
                scenes_info.append({
                    "number": scene.number,
                    "location_id": scene.location_id,
                    "panel_count": len(scene.panels),
                    "character_ids": scene.character_ids,
                })

            chapters_info.append({
                "number": ch.number,
                "title": ch.title,
                "status": ch.status.value,
                "scene_count": len(ch.scenes),
                "panel_count": sum(len(s.panels) for s in ch.scenes),
                "scenes": scenes_info,
            })

        return {
            "story_expanded": True,
            "total_beats": total_beats,
            "generated_chapters": len(chapters_info),
            "remaining_beats": [
                i for i in range(1, total_beats + 1)
                if i not in {c["number"] for c in chapters_info}
            ],
            "chapters": chapters_info,
        }

    def list_chapters(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Chapter], int]:
        """List all chapters with pagination.

        Returns:
            Tuple of (chapters, total_count)
        """
        chapters = self.manager.project.chapters
        total = len(chapters)
        return chapters[offset:offset + limit], total

    def delete_chapter(self, chapter_number: int) -> bool:
        """Delete a chapter by number.

        Returns:
            True if deleted
        """
        chapters = self.manager.project.chapters
        for i, ch in enumerate(chapters):
            if ch.number == chapter_number:
                chapters.pop(i)
                self.manager.save()
                return True
        return False

    def get_remaining_beats(self) -> list[tuple[int, dict]]:
        """Get list of story beats that don't have chapters yet.

        Returns:
            List of (beat_number, beat_info) tuples
        """
        if not self.manager.project.story:
            return []

        existing_numbers = {c.number for c in self.manager.project.chapters}
        remaining = []

        for i, beat in enumerate(self.manager.project.story.story_beats, start=1):
            if i not in existing_numbers:
                remaining.append((i, {
                    "beat": beat.beat,
                    "description": beat.description,
                }))

        return remaining

    async def generate_chapters(
        self,
        beat_numbers: Optional[list[int]] = None,
        panels_per_scene: int = 6,
        feedback: Optional[str] = None,
        on_start: Optional[OnChapterStart] = None,
        on_complete: Optional[OnChapterComplete] = None,
    ) -> list[Chapter]:
        """Generate multiple chapters from story beats.

        Args:
            beat_numbers: Specific beats to generate (None = all remaining)
            panels_per_scene: Target panels per scene
            feedback: Optional feedback for all chapters
            on_start: Callback when chapter generation starts
            on_complete: Callback when chapter is saved

        Returns:
            List of generated chapters
        """
        if beat_numbers is None:
            remaining = self.get_remaining_beats()
            beat_numbers = [num for num, _ in remaining]

        if not beat_numbers:
            return []

        generated = []
        for beat_number in beat_numbers:
            beat = self.get_beat(beat_number)

            if on_start:
                on_start(beat_number, beat)

            chapter = await self.generate_chapter(
                beat_number=beat_number,
                panels_per_scene=panels_per_scene,
                feedback=feedback,
            )

            if on_complete:
                on_complete(chapter)

            generated.append(chapter)

        return generated
