# Claude Code Notes for DreamWright

## Important: Working Directory

**Run commands from the project root (`dreamwright-20251126/`) folder** using the `--project` option, or from inside a project folder.

```bash
# Option 1: Use --project from root directory (recommended)
cd /Users/long/Documents/Github/dreamwright-20251126
dreamwright status --project the-last-hunter
dreamwright generate panels --chapter 1 --project the-last-hunter

# Option 2: cd into project folder
cd projects/the-last-hunter
dreamwright status
dreamwright generate panels --chapter 1
```

The `--project` (or `-p`) option is available on all commands that require a project:
- `dreamwright status -p <project-id>`
- `dreamwright expand -p <project-id>`
- `dreamwright show -p <project-id>`
- `dreamwright generate character -p <project-id>`
- `dreamwright generate location -p <project-id>`
- `dreamwright generate chapter -p <project-id>`
- `dreamwright generate panel -p <project-id>`
- `dreamwright generate panels -p <project-id>`

## Panel Generation

Panels are generated **sequentially** (not in parallel) because:
- Panel N may depend on Panel N-1 for visual continuity
- The `continues_from_previous` flag uses the previous panel as a reference image

**Continuity vs Motion:**
- CONSISTENT: lighting, color palette, background elements, character appearances
- PROGRESSION: characters move/act naturally, expressions evolve
- DO NOT ADD: new props, signs, banners, or objects not in previous panel
- DO NOT REMOVE: existing scene elements from previous panel
- Goal is visual continuity while showing motion, not identical frames

## Project Structure

```
my-project/
├── project.json          # Story data, characters, locations, chapters
└── assets/
    ├── characters/       # Character portraits
    │   └── {name}/
    │       ├── portrait.png
    │       └── portrait.json
    ├── locations/        # Location backgrounds
    │   └── {name}/
    │       ├── day.png
    │       └── day.json
    └── panels/           # Generated panel images
        └── chapter-{n}/
            └── scene-{n}/
                ├── panel-{n}.png
                └── panel-{n}.json
```

## Key Commands

```bash
dreamwright init <name>                              # Create project
dreamwright expand "prompt" --episodes N             # Generate story
dreamwright generate character [--name X]            # Generate character portraits
dreamwright generate location [--name X]             # Generate location backgrounds
dreamwright generate chapter --beat N                # Generate chapter script
dreamwright generate panels --chapter N              # Generate all panels for chapter
dreamwright generate panels --chapter N --scene S    # Generate panels for specific scene
dreamwright status                                   # Show project status
```

## Cache Bypass

Use `--overwrite` flag to bypass cache and regenerate assets:
```bash
dreamwright generate character --name "Mina" --overwrite
dreamwright generate location --name "School" --overwrite
dreamwright generate panels --chapter 1 --overwrite
dreamwright generate panels --chapter 1 --scene 2 --overwrite
```
