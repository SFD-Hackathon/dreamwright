"""DreamWright CLI - AI-powered webtoon and short-form drama production."""

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from dreamwright_generators.script import ScriptGenerator
from dreamwright_generators.character import CharacterGenerator
from dreamwright_generators.location import LocationGenerator
from dreamwright_generators.image import ImageGenerator
from dreamwright_generators.story import StoryGenerator
from dreamwright_core_schemas import (
    Genre,
    ProjectFormat,
    ProjectStatus,
    Tone,
)
from dreamwright_storage import ProjectManager, slugify

app = typer.Typer(
    name="dreamwright",
    help="AI-powered webtoon and short-form drama production",
    no_args_is_help=True,
)
console = Console()

# Subcommands
generate_app = typer.Typer(help="Generate assets")
app.add_typer(generate_app, name="generate")


def get_project_path() -> Path:
    """Get the current project path (current directory)."""
    return Path.cwd()


def parse_panel_id(panel_id: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Parse a panel ID string into chapter, scene, panel numbers.

    Supports formats:
        ch2         -> (2, None, None)
        ch2_s1      -> (2, 1, None)
        ch2_s1_p3   -> (2, 1, 3)

    Args:
        panel_id: The panel ID string to parse

    Returns:
        Tuple of (chapter, scene, panel) where None means not specified

    Raises:
        ValueError: If the format is invalid
    """
    import re

    panel_id = panel_id.strip().lower()

    # Match patterns like ch2, ch2_s1, ch2_s1_p3
    pattern = r'^ch(\d+)(?:_s(\d+))?(?:_p(\d+))?$'
    match = re.match(pattern, panel_id)

    if not match:
        raise ValueError(
            f"Invalid ID format: '{panel_id}'. "
            "Expected format: ch<N>, ch<N>_s<N>, or ch<N>_s<N>_p<N> "
            "(e.g., ch2, ch2_s1, ch2_s1_p3)"
        )

    chapter = int(match.group(1))
    scene = int(match.group(2)) if match.group(2) else None
    panel = int(match.group(3)) if match.group(3) else None

    # Validate: panel requires scene
    if panel is not None and scene is None:
        raise ValueError("Panel number requires scene number (e.g., ch2_s1_p3)")

    return chapter, scene, panel


def resolve_project_path(project: Optional[str] = None) -> Path:
    """Resolve project path from project ID or use current directory.

    Args:
        project: Optional project ID or path. If provided, looks for:
                 1. Exact path if it exists
                 2. projects/{project} relative to current directory
                 3. projects/{project} relative to DREAMRIGHT_ROOT env var
                 If None, uses current working directory.

    Returns:
        Resolved project path.

    Raises:
        typer.Exit: If project cannot be found.
    """
    import os

    if project is None:
        return Path.cwd()

    # Try as exact path first
    project_path = Path(project)
    if project_path.exists() and ProjectManager.exists(project_path):
        return project_path

    # Try relative to current directory's projects folder
    cwd_projects = Path.cwd() / "projects" / project
    if cwd_projects.exists() and ProjectManager.exists(cwd_projects):
        return cwd_projects

    # Try relative to DREAMRIGHT_ROOT env var
    root = os.environ.get("DREAMRIGHT_ROOT")
    if root:
        root_projects = Path(root) / "projects" / project
        if root_projects.exists() and ProjectManager.exists(root_projects):
            return root_projects

    # Not found - show helpful error
    console.print(f"[red]Project '{project}' not found.[/red]")
    console.print("Searched in:")
    console.print(f"  - {project_path}")
    console.print(f"  - {cwd_projects}")
    if root:
        console.print(f"  - {Path(root) / 'projects' / project}")

    # List available projects if projects/ exists
    projects_dir = Path.cwd() / "projects"
    if projects_dir.exists():
        available = [p.name for p in projects_dir.iterdir() if p.is_dir() and ProjectManager.exists(p)]
        if available:
            console.print("\nAvailable projects:")
            for name in sorted(available):
                console.print(f"  - {name}")

    raise typer.Exit(1)


def load_project(project: Optional[str] = None) -> ProjectManager:
    """Load the project from specified path or current directory.

    Args:
        project: Optional project ID or path. See resolve_project_path for details.
    """
    path = resolve_project_path(project)
    if not ProjectManager.exists(path):
        console.print("[red]No project found in current directory.[/red]")
        console.print("Run [cyan]dreamwright init <name>[/cyan] to create a project.")
        raise typer.Exit(1)
    return ProjectManager.load(path)


def run_async(coro):
    """Run an async coroutine.

    Handles both standalone CLI usage and environments with existing event loops
    (Jupyter notebooks, IDEs, etc.) by using nest_asyncio when needed.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            return asyncio.run(coro)
        else:
            # Event loop already running (Jupyter, IDE, etc.)
            # Use nest_asyncio to allow nested event loops
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
    except ValueError as e:
        error_msg = str(e)
        if "GOOGLE_API_KEY" in error_msg:
            console.print("[red]Error: Missing API key[/red]")
            console.print(f"\n{error_msg}")
            console.print("\n[dim]Set your API key with:[/dim]")
            console.print('  export GOOGLE_API_KEY="your-api-key"')
            raise typer.Exit(1)
        raise


@app.command()
def init(
    name: str = typer.Argument(..., help="Project name"),
    format: ProjectFormat = typer.Option(
        ProjectFormat.WEBTOON,
        "--format", "-f",
        help="Project format",
        case_sensitive=False,
        show_choices=True,
    ),
    path: Optional[Path] = typer.Option(None, help="Project directory (defaults to current dir if empty, else ./projects/<name>)"),
):
    """Initialize a new DreamWright project."""
    if path is None:
        cwd = Path.cwd()
        # Use current directory if it's empty or only has hidden files
        if not any(f for f in cwd.iterdir() if not f.name.startswith('.')):
            path = cwd
        else:
            path = cwd / "projects" / name.lower().replace(" ", "-")

    if path.exists() and any(f for f in path.iterdir() if not f.name.startswith('.')):
        console.print(f"[red]Directory {path} already exists and is not empty.[/red]")
        raise typer.Exit(1)

    with console.status(f"Creating project '{name}'..."):
        manager = ProjectManager.create(path, name, format.value)

    console.print(f"[green]Project '{name}' created at {path}[/green]")
    console.print("\nNext steps:")
    console.print(f"  1. cd {path}")
    console.print('  2. dreamwright expand "Your story idea..."')


def parse_character_spec(spec: str) -> tuple[str, Optional[Path]]:
    """Parse a character specification string.

    Formats:
        "Name" -> (Name, None)
        "Name:path/to/image.png" -> (Name, Path)

    Returns:
        Tuple of (name, optional_image_path)
    """
    if ":" in spec:
        parts = spec.split(":", 1)
        name = parts[0].strip()
        image_path = Path(parts[1].strip())
        return name, image_path
    return spec.strip(), None


@app.command()
def expand(
    prompt: str = typer.Argument(..., help="Story prompt/idea to expand"),
    genre: Optional[str] = typer.Option(None, help="Genre hint (romance, action, fantasy, etc.)"),
    tone: Optional[str] = typer.Option(None, help="Tone hint (comedic, dramatic, dark, etc.)"),
    episodes: int = typer.Option(10, help="Target number of episodes"),
    character: Optional[list[str]] = typer.Option(None, "--character", "-c", help="Character to include (format: 'Name' or 'Name:path/to/image.png')"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID or path (uses current directory if not specified)"),
):
    """Expand a story prompt into full story structure.

    Use --character to specify characters that MUST be included in the story.
    You can also provide a reference image for each character.

    Examples:
        dreamwright expand "A story about..." --character "Lily"
        dreamwright expand "A story about..." -c "Lily:/path/to/image.png" -c "Max"
    """
    # Parse character specifications
    character_specs: list[tuple[str, Optional[Path]]] = []
    if character:
        for spec in character:
            name, image_path = parse_character_spec(spec)
            if image_path and not image_path.exists():
                console.print(f"[red]Error: Character image not found: {image_path}[/red]")
                raise typer.Exit(1)
            character_specs.append((name, image_path))

        console.print("[cyan]Characters to include:[/cyan]")
        for name, img in character_specs:
            if img:
                console.print(f"  - {name} (reference: {img})")
            else:
                console.print(f"  - {name}")

    manager = load_project(project)

    # Parse hints
    genre_hint = None
    if genre:
        try:
            genre_hint = Genre(genre.lower())
        except ValueError:
            console.print(f"[yellow]Unknown genre '{genre}', will let AI decide.[/yellow]")

    tone_hint = None
    if tone:
        try:
            tone_hint = Tone(tone.lower())
        except ValueError:
            console.print(f"[yellow]Unknown tone '{tone}', will let AI decide.[/yellow]")

    console.print(Panel(prompt, title="Story Prompt", border_style="blue"))

    # Extract character names for the generator
    predefined_char_names = [name for name, _ in character_specs] if character_specs else None
    # Build lookup from character name to reference image
    char_refs = {name.lower(): img for name, img in character_specs if img} if character_specs else {}

    async def do_expand_and_generate():
        """Expand story and generate character sheets in one async context."""
        from dreamwright_services import CharacterService

        # Step 1: Expand story
        generator = StoryGenerator()
        story, characters, locations = await generator.expand(
            prompt=prompt,
            genre_hint=genre_hint,
            tone_hint=tone_hint,
            episode_count=episodes,
            predefined_characters=predefined_char_names,
        )

        # Step 2: Generate character sheets from references (if any)
        chars_to_generate = []
        if char_refs:
            for char in characters:
                ref_img = char_refs.get(char.name.lower())
                if ref_img:
                    chars_to_generate.append((char, ref_img))

        return story, characters, locations, chars_to_generate

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Expanding story with AI...", total=None)
        story, characters, locations, chars_to_generate = run_async(do_expand_and_generate())

    # Update project
    manager.project.original_prompt = prompt
    manager.project.story = story
    manager.project.characters = characters
    manager.project.locations = locations
    manager.project.status = ProjectStatus.IN_PROGRESS
    manager.save()

    # Display results
    console.print("\n[green]Story expanded successfully![/green]\n")

    # Process character reference images (generate styled character sheets)
    if chars_to_generate:
        from dreamwright_services import CharacterService
        service = CharacterService(manager)

        console.print("\n[cyan]Generating character sheets from reference images...[/cyan]")

        async def generate_from_refs():
            for char, ref_img in chars_to_generate:
                console.print(f"  [dim]Processing {char.name} with reference...[/dim]")
                try:
                    await service.generate_asset(
                        char.id,
                        style="webtoon",
                        overwrite=True,
                        reference_image=ref_img,
                    )
                    console.print(f"  [green]✓ {char.name} sheet generated[/green]")
                except Exception as e:
                    console.print(f"  [red]✗ {char.name} failed: {e}[/red]")

        run_async(generate_from_refs())

    console.print(Panel(
        f"[bold]{story.title}[/bold]\n\n{story.logline}",
        title="Story",
        border_style="green",
    ))

    console.print(f"\n[cyan]Genre:[/cyan] {story.genre.value}")
    console.print(f"[cyan]Tone:[/cyan] {story.tone.value}")
    console.print(f"[cyan]Themes:[/cyan] {', '.join(story.themes)}")
    console.print(f"[cyan]Episodes:[/cyan] {story.episode_count}")

    # Characters table
    if characters:
        console.print("\n[bold]Characters:[/bold]")
        char_table = Table(show_header=True)
        char_table.add_column("Name")
        char_table.add_column("Role")
        char_table.add_column("Age")
        char_table.add_column("Description")

        for char in characters:
            char_table.add_row(
                char.name,
                char.role.value,
                char.age,
                char.description.physical[:50] + "..." if len(char.description.physical) > 50 else char.description.physical,
            )
        console.print(char_table)

    # Locations table
    if locations:
        console.print("\n[bold]Locations:[/bold]")
        loc_table = Table(show_header=True)
        loc_table.add_column("Name")
        loc_table.add_column("Type")
        loc_table.add_column("Description")

        for loc in locations:
            loc_table.add_row(
                loc.name,
                loc.type.value,
                loc.description[:50] + "..." if len(loc.description) > 50 else loc.description,
            )
        console.print(loc_table)

    console.print("\n[dim]Next: dreamwright generate character --name <name>[/dim]")


@generate_app.command("character")
def generate_character(
    name: Optional[str] = typer.Option(None, help="Character name (generates all if not specified)"),
    style: str = typer.Option("webtoon", help="Art style"),
    reference: Optional[Path] = typer.Option(None, "--reference", "-r", help="Input image to use as reference"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Regenerate even if exists (bypass cache)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID or path (uses current directory if not specified)"),
):
    """Generate character reference sheets (full-body three-view turnaround).

    Creates a single image showing front, side, and back views of each character.
    This provides the best reference for panel generation with consistent
    costume and appearance from all angles.

    Use --reference to provide an input photo/image that the AI will use as
    a reference when generating the character's appearance.
    """
    from dreamwright_services import CharacterService
    from dreamwright_services.exceptions import NotFoundError

    # Validate reference option
    if reference:
        if not name:
            console.print("[red]Error: --reference requires --name (can't use reference for all characters)[/red]")
            raise typer.Exit(1)
        if not reference.exists():
            console.print(f"[red]Error: Reference image not found: {reference}[/red]")
            raise typer.Exit(1)
        console.print(f"[cyan]Using reference image:[/cyan] {reference}")

    manager = load_project(project)
    service = CharacterService(manager)

    if not manager.project.characters:
        console.print("[red]No characters found. Run 'dreamwright expand' first.[/red]")
        raise typer.Exit(1)

    # Find character(s) to generate
    if name:
        try:
            char = service.get_character_by_name(name)
            character_ids = [char.id]
        except NotFoundError:
            console.print(f"[red]Character '{name}' not found.[/red]")
            console.print("Available characters:")
            for c in manager.project.characters:
                console.print(f"  - {c.name}")
            raise typer.Exit(1)
    else:
        character_ids = None  # Generate all

    # Callbacks for progress
    def on_start(char):
        console.print(f"\n[cyan]Generating assets for {char.name}...[/cyan]")

    def on_progress(step_desc):
        console.print(f"  [dim]{step_desc}[/dim]")

    def on_complete(char, path):
        console.print(f"  [green]Complete! Sheet saved: {path}[/green]")

    def on_skip(char, reason):
        console.print(f"\n[dim]{char.name}: assets already exist (use --overwrite to regenerate)[/dim]")

    async def do_generate():
        if character_ids:
            # Single character
            return await service.generate_asset(
                character_ids[0],
                style=style,
                overwrite=overwrite,
                reference_image=reference,
                on_start=on_start,
                on_complete=on_complete,
                on_progress=on_progress,
            )
        else:
            # All characters
            return await service.generate_all_assets(
                style=style,
                overwrite=overwrite,
                on_start=on_start,
                on_complete=on_complete,
                on_skip=on_skip,
                on_progress=on_progress,
            )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Generating character sheets...", total=None)
        run_async(do_generate())

    console.print("\n[green]Character generation complete![/green]")
    console.print("[dim]Next: dreamwright generate location --name <name>[/dim]")


@generate_app.command("location")
def generate_location(
    name: Optional[str] = typer.Option(None, help="Location name (generates all if not specified)"),
    style: str = typer.Option("webtoon", help="Art style"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Regenerate even if exists (bypass cache)"),
    sheet: bool = typer.Option(False, "--sheet", help="Generate multi-angle reference sheet (2x2 grid)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID or path (uses current directory if not specified)"),
):
    """Generate location/background visual assets.

    By default generates single reference images. Use --sheet to generate
    multi-angle reference sheets showing wide, high angle, close-up, and low angle views.
    """
    from dreamwright_services import LocationService
    from dreamwright_services.exceptions import NotFoundError

    manager = load_project(project)
    service = LocationService(manager)

    if not manager.project.locations:
        console.print("[red]No locations found. Run 'dreamwright expand' first.[/red]")
        raise typer.Exit(1)

    # Find location(s) to generate
    if name:
        try:
            loc = service.get_location_by_name(name)
            location_ids = [loc.id]
        except NotFoundError:
            console.print(f"[red]Location '{name}' not found.[/red]")
            console.print("Available locations:")
            for l in manager.project.locations:
                console.print(f"  - {l.name}")
            raise typer.Exit(1)
    else:
        location_ids = [l.id for l in manager.project.locations]

    asset_type = "reference sheet" if sheet else "reference"

    # Callbacks for progress
    def on_start(loc):
        console.print(f"\n[cyan]Generating {loc.name} {asset_type}...[/cyan]")

    def on_complete(loc, path):
        console.print(f"  [green]Saved: {path}[/green]")

    def on_skip(loc, reason):
        console.print(f"\n[dim]{loc.name}: {asset_type} already exists (use --overwrite to regenerate)[/dim]")

    async def do_generate():
        results = []
        for loc_id in location_ids:
            loc = service.get_location(loc_id)

            # Check if asset exists
            if sheet:
                existing = loc.assets.reference_sheet
            else:
                existing = loc.assets.reference

            if existing and not overwrite:
                on_skip(loc, "asset_exists")
                results.append({"location_id": loc_id, "skipped": True, "path": existing})
                continue

            try:
                if sheet:
                    result = await service.generate_reference_sheet(
                        loc_id,
                        style=style,
                        overwrite=overwrite,
                        on_start=on_start,
                        on_complete=on_complete,
                    )
                else:
                    result = await service.generate_asset(
                        loc_id,
                        style=style,
                        overwrite=overwrite,
                        on_start=on_start,
                        on_complete=on_complete,
                    )
                results.append(result)
            except Exception as e:
                console.print(f"  [red]Error: {e}[/red]")
                results.append({"location_id": loc_id, "error": str(e)})
        return results

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(f"Generating location {asset_type}s...", total=None)
        run_async(do_generate())

    console.print(f"\n[green]Location {asset_type} generation complete![/green]")
    console.print("[dim]Next: dreamwright generate script --chapter 1[/dim]")


def confirm_prompt(prompt: str, title: str = "PROMPT") -> bool:
    """Display a prompt and ask for user confirmation."""
    console.print(f"\n[bold cyan]{'─' * 60}[/bold cyan]")
    console.print(f"[bold cyan]{title}[/bold cyan]")
    console.print(f"[bold cyan]{'─' * 60}[/bold cyan]")
    console.print(prompt)
    console.print(f"[bold cyan]{'─' * 60}[/bold cyan]\n")

    return typer.confirm("Proceed with this prompt?", default=True)


def confirm_result(result: str, title: str = "RESULT") -> bool:
    """Display a result and ask for user confirmation."""
    console.print(f"\n[bold green]{'─' * 60}[/bold green]")
    console.print(f"[bold green]{title}[/bold green]")
    console.print(f"[bold green]{'─' * 60}[/bold green]")
    console.print(result)
    console.print(f"[bold green]{'─' * 60}[/bold green]\n")

    return typer.confirm("Accept this result?", default=True)


# =============================================================================
# UNIFIED GENERATE COMMANDS
# =============================================================================

@generate_app.command("script")
def generate_script_cmd(
    id: Optional[str] = typer.Argument(None, help="Panel ID (e.g., ch2, ch2_s1, ch2_s1_p3)"),
    chapter: Optional[int] = typer.Option(None, "--chapter", "-c", help="Chapter number (generates from story beat)"),
    scene: Optional[int] = typer.Option(None, "--scene", "-s", help="Scene number (requires --chapter)"),
    panel: Optional[int] = typer.Option(None, "--panel", "-n", help="Panel number (requires --scene)"),
    all_chapters: bool = typer.Option(False, "--all", "-a", help="Generate all remaining chapters"),
    panels_per_scene: int = typer.Option(6, help="Target panels per scene"),
    feedback: Optional[str] = typer.Option(None, "--feedback", "-f", help="Feedback to guide generation"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID or path"),
):
    """Generate or regenerate script at chapter, scene, or panel level.

    Script generation creates the storyboard structure (scenes, panels, dialogue,
    actions, camera directions). Image generation depends on script being ready.

    Examples:
        dreamwright generate script ch2                      # Generate chapter 2 from story beat
        dreamwright generate script ch2_s1                   # Regenerate scene 1 script
        dreamwright generate script ch2_s1_p3                # Regenerate panel 3 script
        dreamwright generate script --all                    # Generate all remaining chapters
        dreamwright generate script ch2 -f "More action"     # With feedback
    """
    # Parse ID argument if provided
    if id:
        try:
            id_chapter, id_scene, id_panel = parse_panel_id(id)
            # ID takes precedence, but warn if flags also provided
            if chapter is not None or scene is not None or panel is not None:
                console.print("[yellow]Warning: ID argument overrides --chapter/--scene/--panel flags[/yellow]")
            chapter = id_chapter
            scene = id_scene
            panel = id_panel
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)
    # Validate option combinations
    if all_chapters and chapter is not None:
        console.print("[red]Error: --all cannot be used with chapter ID or --chapter[/red]")
        raise typer.Exit(1)

    from dreamwright_services import ScriptService
    from dreamwright_services.exceptions import DependencyError, NotFoundError, ValidationError

    manager = load_project(project)
    service = ScriptService(manager)

    # No arguments - show status
    if not all_chapters and chapter is None:
        status = service.get_script_status()
        if not status["story_expanded"]:
            console.print("[red]No story found. Run 'dreamwright expand' first.[/red]")
            raise typer.Exit(1)

        console.print("\n[bold]Script Status:[/bold]")
        story = manager.project.story
        existing_numbers = {c.number for c in manager.project.chapters}
        for i, beat in enumerate(story.story_beats, start=1):
            existing = i in existing_numbers
            status_mark = "[green]✓[/green]" if existing else "[dim]○[/dim]"
            console.print(f"  {status_mark} Chapter {i}: {beat.beat}")

        console.print(f"\n[dim]{status['generated_chapters']}/{status['total_beats']} chapters generated.[/dim]")
        if status["remaining_beats"]:
            console.print("[dim]Use --chapter N or --all to generate.[/dim]")
        raise typer.Exit(0)

    try:
        if panel is not None:
            # Panel-level regeneration
            console.print(f"[cyan]Regenerating Panel {panel} script in Chapter {chapter}, Scene {scene}[/cyan]")
            if feedback:
                console.print(f"  [dim]Feedback: {feedback}[/dim]")

            async def do_panel():
                return await service.regenerate_panel(chapter, scene, panel, feedback=feedback)

            new_panel = run_async(do_panel())
            console.print(f"\n[green]Panel {panel} script regenerated![/green]")
            console.print(f"  Action: {new_panel.action[:80]}...")
            chars = ", ".join(f"{pc.character_id}" for pc in new_panel.characters)
            if chars:
                console.print(f"  Characters: {chars}")

        elif scene is not None:
            # Scene-level regeneration
            console.print(f"[cyan]Regenerating Scene {scene} script in Chapter {chapter}[/cyan]")
            if feedback:
                console.print(f"  [dim]Feedback: {feedback}[/dim]")

            async def do_scene():
                return await service.regenerate_scene(chapter, scene, panels_per_scene, feedback=feedback)

            new_scene = run_async(do_scene())
            console.print(f"\n[green]Scene {scene} script regenerated![/green]")
            console.print(f"  Panels: {len(new_scene.panels)}")
            console.print(f"  Location: {new_scene.location_id}")

        elif all_chapters:
            # Generate all remaining chapters
            remaining = service.get_remaining_beats()
            if not remaining:
                console.print("[green]All chapters already generated![/green]")
                raise typer.Exit(0)

            console.print(f"[cyan]Generating {len(remaining)} remaining chapter(s)...[/cyan]")

            def on_start(num, beat):
                console.print(f"\n  [bold]Chapter {num}:[/bold] {beat.beat}")

            def on_complete(ch):
                console.print(f"    [green]✓[/green] {ch.title} ({len(ch.scenes)} scenes)")

            async def do_all():
                return await service.generate_chapters(
                    panels_per_scene=panels_per_scene,
                    feedback=feedback,
                    on_start=on_start,
                    on_complete=on_complete,
                )

            chapters = run_async(do_all())
            console.print(f"\n[green]Generated {len(chapters)} chapter(s)![/green]")

        else:
            # Single chapter generation
            console.print(f"[cyan]Generating Chapter {chapter} script...[/cyan]")
            if feedback:
                console.print(f"  [dim]Feedback: {feedback}[/dim]")

            async def do_chapter():
                return await service.generate_chapter(chapter, panels_per_scene, feedback=feedback)

            new_chapter = run_async(do_chapter())
            console.print(f"\n[green]Chapter {chapter} generated![/green]")
            console.print(f"  Title: {new_chapter.title}")
            console.print(f"  Scenes: {len(new_chapter.scenes)}")
            total_panels = sum(len(s.panels) for s in new_chapter.scenes)
            console.print(f"  Panels: {total_panels}")

        console.print("\n[dim]Next: dreamwright generate image --chapter N[/dim]")

    except NotFoundError as e:
        console.print(f"[red]Error: {e.resource_type} {e.resource_id} not found[/red]")
        raise typer.Exit(1)
    except ValidationError as e:
        console.print(f"[red]Error: {e.message}[/red]")
        raise typer.Exit(1)
    except DependencyError as e:
        console.print(f"[red]Error: {e.message}[/red]")
        for dep in e.missing_dependencies:
            console.print(f"  - {dep['message']}")
        raise typer.Exit(1)


@generate_app.command("image")
def generate_image_cmd(
    id: Optional[str] = typer.Argument(None, help="Panel ID (e.g., ch2, ch2_s1, ch2_s1_p3)"),
    chapter: Optional[int] = typer.Option(None, "--chapter", "-c", help="Chapter number"),
    scene: Optional[int] = typer.Option(None, "--scene", "-s", help="Scene number (generates only this scene)"),
    panel: Optional[int] = typer.Option(None, "--panel", "-n", help="Panel number (requires --scene)"),
    style: str = typer.Option("webtoon", help="Art style"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Regenerate even if images exist"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID or path"),
):
    """Generate panel images at chapter, scene, or panel level.

    Image generation requires:
    - Script (chapter/scene/panel must exist)
    - Character reference assets
    - Location reference assets

    Examples:
        dreamwright generate image ch2                      # Generate all chapter 2 images
        dreamwright generate image ch2_s1                   # Generate scene 1 images
        dreamwright generate image ch2_s1_p3                # Generate single panel image
        dreamwright generate image ch2 --overwrite          # Regenerate all
        dreamwright generate image --chapter 1 --scene 4    # Using flags instead
    """
    # Parse ID argument if provided
    if id:
        try:
            id_chapter, id_scene, id_panel = parse_panel_id(id)
            # ID takes precedence, but warn if flags also provided
            if chapter is not None or scene is not None or panel is not None:
                console.print("[yellow]Warning: ID argument overrides --chapter/--scene/--panel flags[/yellow]")
            chapter = id_chapter
            scene = id_scene
            panel = id_panel
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)

    # Require chapter
    if chapter is None:
        console.print("[red]Error: Chapter is required. Use ID (e.g., ch2) or --chapter flag.[/red]")
        raise typer.Exit(1)
    from dreamwright_generators.image import PanelResult
    from dreamwright_services import ImageService
    from dreamwright_services.exceptions import DependencyError, NotFoundError

    manager = load_project(project)
    service = ImageService(manager)

    # Validate options
    if panel is not None and scene is None:
        console.print("[red]Error: --panel requires --scene[/red]")
        raise typer.Exit(1)

    # Validate chapter exists
    try:
        target_chapter = service.get_chapter(chapter)
    except NotFoundError:
        console.print(f"[red]Chapter {chapter} not found.[/red]")
        console.print("[dim]Generate script first: dreamwright generate script --chapter N[/dim]")
        raise typer.Exit(1)

    # Validate scene exists if specified
    if scene is not None:
        try:
            target_scene = service.get_scene(chapter, scene)
        except NotFoundError:
            console.print(f"[red]Scene {scene} not found in Chapter {chapter}.[/red]")
            raise typer.Exit(1)

        # Validate panel exists if specified
        if panel is not None:
            try:
                service.get_panel(chapter, scene, panel)
            except NotFoundError:
                console.print(f"[red]Panel {panel} not found in Scene {scene}.[/red]")
                raise typer.Exit(1)

    # Validate dependencies
    missing = service.validate_dependencies(chapter, scene)
    if missing:
        console.print("[red]Error: Missing required assets.[/red]\n")
        char_deps = [d for d in missing if "character" in d["type"]]
        loc_deps = [d for d in missing if "location" in d["type"]]

        if char_deps:
            console.print("[yellow]Missing character assets:[/yellow]")
            for dep in char_deps:
                console.print(f"  - {dep['message']}")
            console.print("  [dim]Run: dreamwright generate character[/dim]")

        if loc_deps:
            console.print("[yellow]Missing location assets:[/yellow]")
            for dep in loc_deps:
                console.print(f"  - {dep['message']}")
            console.print("  [dim]Run: dreamwright generate location[/dim]")

        raise typer.Exit(1)

    # Progress callbacks
    def on_scene_start(s):
        desc = s.description[:50] + "..." if len(s.description) > 50 else s.description
        console.print(f"\n  [bold]Scene {s.number}[/bold]: {desc}")

    def on_panel_start(p):
        console.print(f"    Panel {p.number}: [cyan]generating...[/cyan]", end="")

    def on_panel_complete(result: PanelResult):
        if result.skipped:
            console.print(f"\r    Panel {result.panel.number}: [dim]exists (skipped)[/dim]")
        elif result.error:
            console.print(f"\r    Panel {result.panel.number}: [red]failed[/red]")
        else:
            console.print(f"\r    Panel {result.panel.number}: [green]saved[/green]           ")

    # Generate based on level
    if panel is not None:
        # Single panel
        console.print(f"\n[cyan]Generating Panel {panel} image (Chapter {chapter}, Scene {scene})[/cyan]")

        async def do_panel():
            return await service.generate_single_panel(
                chapter, scene, panel,
                style=style, overwrite=overwrite,
                on_panel_start=on_panel_start,
                on_panel_complete=on_panel_complete,
            )

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            progress.add_task("Generating...", total=None)
            result = run_async(do_panel())

        if result.error:
            console.print(f"\n[red]Failed: {result.error}[/red]")
            raise typer.Exit(1)
        elif result.skipped:
            console.print(f"\n[yellow]Panel exists (use --overwrite to regenerate)[/yellow]")
        else:
            console.print(f"\n[green]Panel generated![/green]")
            console.print(f"  Output: {result.panel.image_path}")

    else:
        # Scene or chapter level
        if scene is not None:
            total = len(target_scene.panels)
            console.print(f"\n[cyan]Generating {total} panel images for Scene {scene}[/cyan]")
        else:
            total = sum(len(s.panels) for s in target_chapter.scenes)
            console.print(f"\n[cyan]Generating {total} panel images for Chapter {chapter}[/cyan]")

        async def do_generate():
            return await service.generate_panels(
                chapter_number=chapter,
                scene_number=scene,
                style=style,
                overwrite=overwrite,
                on_scene_start=on_scene_start,
                on_panel_start=on_panel_start,
                on_panel_complete=on_panel_complete,
            )

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            progress.add_task("Generating...", total=None)
            result = run_async(do_generate())

        console.print(f"\n[green]Image generation complete![/green]")
        console.print(f"  Generated: {result['generated_count']}")
        console.print(f"  Skipped: {result['skipped_count']}")
        if result.get('error_count', 0) > 0:
            console.print(f"  [red]Errors: {result['error_count']}[/red]")


@app.command()
def status(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID or path (uses current directory if not specified)"),
):
    """Show project status."""
    manager = load_project(project)
    proj = manager.project

    console.print(Panel(
        f"[bold]{proj.name}[/bold]\n"
        f"Format: {proj.format.value}\n"
        f"Status: {proj.status.value}\n"
        f"Created: {proj.created_at.strftime('%Y-%m-%d %H:%M')}",
        title="Project",
        border_style="blue",
    ))

    if proj.story:
        console.print(f"\n[cyan]Story:[/cyan] {proj.story.title}")
        console.print(f"[cyan]Logline:[/cyan] {proj.story.logline}")

    console.print(f"\n[cyan]Characters:[/cyan] {len(proj.characters)}")
    for char in proj.characters:
        has_portrait = "[green]P[/green]" if char.assets.portrait else "[dim]-[/dim]"
        console.print(f"  {has_portrait} {char.name} ({char.role.value})")

    console.print(f"\n[cyan]Locations:[/cyan] {len(proj.locations)}")
    for loc in proj.locations:
        has_ref = "[green]R[/green]" if loc.assets.reference else "[dim]-[/dim]"
        console.print(f"  {has_ref} {loc.name} ({loc.type.value})")

    console.print(f"\n[cyan]Chapters:[/cyan] {len(proj.chapters)}")

    # Count generated assets
    assets_path = manager.storage.assets_path
    if assets_path.exists():
        panels_dir = assets_path / "panels"
        if panels_dir.exists():
            panel_count = sum(1 for _ in panels_dir.rglob("*.png"))
        else:
            panel_count = 0
        console.print(f"\n[cyan]Generated panels:[/cyan] {panel_count}")


@app.command()
def show(
    entity: str = typer.Argument(..., help="Entity to show (story, character:<name>, location:<name>)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID or path (uses current directory if not specified)"),
):
    """Show detailed information about an entity."""
    manager = load_project(project)

    if entity == "story":
        if not manager.project.story:
            console.print("[red]No story expanded yet.[/red]")
            raise typer.Exit(1)

        story = manager.project.story
        console.print(Panel(
            f"[bold]{story.title}[/bold]\n\n{story.logline}",
            title="Story",
            border_style="green",
        ))
        console.print(f"\n[cyan]Genre:[/cyan] {story.genre.value}")
        console.print(f"[cyan]Tone:[/cyan] {story.tone.value}")
        console.print(f"[cyan]Themes:[/cyan] {', '.join(story.themes)}")
        console.print(f"[cyan]Target Audience:[/cyan] {story.target_audience}")
        console.print(f"[cyan]Episodes:[/cyan] {story.episode_count}")

        console.print("\n[bold]Synopsis:[/bold]")
        console.print(story.synopsis)

        if story.story_beats:
            console.print("\n[bold]Story Beats:[/bold]")
            for beat in story.story_beats:
                console.print(f"  [cyan]{beat.beat}:[/cyan] {beat.description}")

    elif entity.startswith("character:"):
        name = entity.split(":", 1)[1]
        char = manager.project.get_character_by_name(name)
        if not char:
            console.print(f"[red]Character '{name}' not found.[/red]")
            raise typer.Exit(1)

        console.print(Panel(
            f"[bold]{char.name}[/bold] ({char.role.value})\nAge: {char.age}",
            title="Character",
            border_style="green",
        ))
        console.print(f"\n[cyan]Physical:[/cyan] {char.description.physical}")
        console.print(f"[cyan]Personality:[/cyan] {char.description.personality}")
        console.print(f"[cyan]Background:[/cyan] {char.description.background}")
        console.print(f"[cyan]Motivation:[/cyan] {char.description.motivation}")
        console.print(f"\n[cyan]Visual Tags:[/cyan] {', '.join(char.visual_tags)}")

        if char.assets.portrait:
            console.print(f"\n[cyan]Portrait:[/cyan] {char.assets.portrait}")

    elif entity.startswith("location:"):
        name = entity.split(":", 1)[1]
        loc = manager.project.get_location_by_name(name)
        if not loc:
            console.print(f"[red]Location '{name}' not found.[/red]")
            raise typer.Exit(1)

        console.print(Panel(
            f"[bold]{loc.name}[/bold] ({loc.type.value})",
            title="Location",
            border_style="green",
        ))
        console.print(f"\n[cyan]Description:[/cyan] {loc.description}")
        console.print(f"\n[cyan]Visual Tags:[/cyan] {', '.join(loc.visual_tags)}")

        if loc.assets.reference:
            console.print(f"\n[cyan]Reference:[/cyan] {loc.assets.reference}")

    else:
        console.print(f"[red]Unknown entity: {entity}[/red]")
        console.print("Use: story, character:<name>, or location:<name>")
        raise typer.Exit(1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development"),
    projects_dir: Optional[Path] = typer.Option(None, help="Directory for storing projects"),
):
    """Start the DreamWright API server."""
    import uvicorn

    from dreamwright_api.app import create_app
    from dreamwright_api.deps import settings

    # Configure projects directory
    if projects_dir:
        settings.projects_dir = projects_dir
    else:
        settings.projects_dir = Path.cwd() / "projects"

    console.print(f"\n[bold]DreamWright API Server[/bold]")
    console.print(f"  Projects: {settings.projects_dir}")
    console.print(f"  URL: http://{host}:{port}")
    console.print(f"  Docs: http://{host}:{port}/docs")
    console.print()

    if reload:
        uvicorn.run(
            "dreamwright_api.app:app",
            host=host,
            port=port,
            reload=True,
        )
    else:
        app_instance = create_app(projects_dir=settings.projects_dir)
        uvicorn.run(app_instance, host=host, port=port)


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
