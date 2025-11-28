# Claude Code Notes for DreamWright

## Important: Running Commands

**Use the virtual environment's dreamwright command:**
```bash
/Users/long/Documents/Github/dreamwright/.venv/bin/dreamwright <command>
```

Or activate the venv first:
```bash
source /Users/long/Documents/Github/dreamwright/.venv/bin/activate
dreamwright <command>
```

**Run from the project root** using the `--project` (or `-p`) option:

```bash
# From root directory (recommended)
dreamwright status -p dragon-mishap
dreamwright generate image --chapter 1 -p dragon-mishap

# Or cd into project folder
cd projects/dragon-mishap
dreamwright status
dreamwright generate image --chapter 1
```

The `-p/--project` option is available on all commands that require a project:
- `dreamwright status -p <project-id>`
- `dreamwright expand -p <project-id>`
- `dreamwright show -p <project-id>`
- `dreamwright generate character -p <project-id>`
- `dreamwright generate location -p <project-id>`
- `dreamwright generate script -p <project-id>`
- `dreamwright generate image -p <project-id>`

## Panel Generation

Panels are generated **sequentially** (not in parallel) because:
- Panel N may depend on Panel N-1 for visual continuity
- The `continues_from_previous` flag uses the previous panel as a reference image

**Character-Specific Priority:**
- If a character WAS in the previous panel → previous panel is highest priority (match exactly)
- If a character was NOT in the previous panel → character reference sheet is highest priority
- This ensures characters maintain consistency even when entering/leaving scenes

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
dreamwright generate character [--name X]            # Generate character sheets
dreamwright generate character --name X -r photo.png # Use reference photo
dreamwright generate location [--name X]             # Generate location backgrounds
dreamwright generate script ch1                      # Generate chapter 1 script
dreamwright generate image ch1                       # Generate all chapter 1 images
dreamwright generate image ch2_s1                    # Generate scene 1 images
dreamwright generate image ch2_s1_p3                 # Generate single panel image
dreamwright status                                   # Show project status
```

## Reference Images

### During Story Expansion
Use `--character` (or `-c`) to specify characters with reference images when creating a story:
```bash
dreamwright expand "A story about a young artist" -c "Lily:/path/to/photo.png" -c "Max" -p my-project
```
- Characters are automatically included in the generated story
- Reference images are processed into webtoon-style character sheets
- You can mix characters with and without reference images

### For Existing Characters
Use `--reference` (or `-r`) to regenerate a character using a reference photo:
```bash
dreamwright generate character --name "Lily" -r /path/to/reference.png -p dragon-mishap
```
The AI will use this image as a reference for the character's appearance.

## ID Syntax

Use shorthand IDs instead of verbose flags:
- `ch2` → chapter 2
- `ch2_s1` → chapter 2, scene 1
- `ch2_s1_p3` → chapter 2, scene 1, panel 3

```bash
# These are equivalent:
dreamwright generate image ch2_s1_p3 -p dragon-mishap
dreamwright generate image -c 2 -s 1 -n 3 -p dragon-mishap
```

## Cache Bypass

Use `--overwrite` flag to bypass cache and regenerate assets:
```bash
dreamwright generate character --name "Mina" --overwrite
dreamwright generate location --name "School" --overwrite
dreamwright generate image ch1 --overwrite
dreamwright generate image ch1_s2 --overwrite
```
