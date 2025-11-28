#!/usr/bin/env python3
"""
Upload dreamwright projects to R2 bucket for webtoon showcase.
Transforms project.json to webtoon.json format.

Usage:
    python upload_projects.py                    # Upload all projects
    python upload_projects.py dragon-mishap      # Upload specific project
    python upload_projects.py project1 project2  # Upload multiple projects

Environment variables (or .env file):
    CLOUDFLARE_ACCOUNT_ID   - Your Cloudflare account ID
    R2_ACCESS_KEY_ID        - R2 API token access key ID
    R2_SECRET_ACCESS_KEY    - R2 API token secret access key

To create R2 API credentials:
    1. Go to Cloudflare Dashboard > R2 > Manage R2 API Tokens
    2. Create a new API token with "Object Read & Write" permissions
    3. Copy the Access Key ID and Secret Access Key
"""

import argparse
import json
import mimetypes
import os
import re
import sys
from pathlib import Path

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("Error: boto3 is required. Install with: pip install boto3")
    sys.exit(1)

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Look for .env in script directory or parent directories
    script_dir = Path(__file__).parent
    for env_path in [script_dir / ".env", script_dir.parent / ".env"]:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass  # dotenv not installed, rely on environment variables

PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", "/Users/long/Documents/Github/dreamwright/projects"))
BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "webtoons-showcase")

# R2 configuration
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")

# Global S3 client (initialized lazily)
_s3_client = None


def get_s3_client():
    """Get or create S3 client for R2."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client

    if not all([CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
        print("Error: Missing required environment variables.")
        print("Please set the following:")
        print("  CLOUDFLARE_ACCOUNT_ID - Your Cloudflare account ID")
        print("  R2_ACCESS_KEY_ID      - R2 API token access key ID")
        print("  R2_SECRET_ACCESS_KEY  - R2 API token secret access key")
        print("\nYou can also create a .env file in the scripts directory.")
        sys.exit(1)

    _s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "adaptive"}
        ),
    )
    return _s3_client


def transform_project_to_webtoon(project_data: dict) -> dict:
    """Transform project.json format to webtoon.json format."""
    story = project_data.get("story", {})

    # Transform characters
    characters = []
    for char in project_data.get("characters", []):
        char_id = char["id"].replace("char_", "")
        desc = char.get("description", {})

        # Clean visual traits - remove AI prompt instructions
        visual_tags = char.get("visual_tags", [])[:3]
        cleaned_traits = []
        for tag in visual_tags:
            # Remove prompt instructions in parentheses
            clean_tag = re.sub(r'\s*\([^)]*MATCH[^)]*\)', '', tag)
            clean_tag = re.sub(r'\s*\([^)]*EXACTLY[^)]*\)', '', clean_tag)
            clean_tag = re.sub(r'\s*\([^)]*REFERENCE[^)]*\)', '', clean_tag)
            if clean_tag.strip():
                cleaned_traits.append(clean_tag.strip())

        characters.append({
            "id": char_id,
            "name": char["name"],
            "description": desc.get("personality", "") or desc.get("physical", ""),
            "visual_traits": ", ".join(cleaned_traits),
            "age": char.get("age", ""),
            "main": char.get("role") == "protagonist"
        })

    # Transform chapters with scenes and segments
    chapters = []
    for chapter in project_data.get("chapters", []):
        chapter_num = chapter.get("number", 1)
        scenes = []
        for scene in chapter.get("scenes", []):
            scene_num = scene.get("number", 1)
            segments = []
            for panel in scene.get("panels", []):
                # Transform dialogues
                dialogues = []
                for dlg in panel.get("dialogue", []):
                    char_id_raw = dlg.get("character_id") or ""
                    char_id = char_id_raw.replace("char_", "") if char_id_raw else ""
                    dialogues.append({
                        "character_id": char_id,
                        "text": dlg.get("text", ""),
                        "type": dlg.get("type", "speech")
                    })

                # Generate segment ID that matches uploaded image filename
                panel_num = panel.get("number", 0)
                segment_id = f"ch{chapter_num}_s{scene_num}_p{panel_num}"

                segments.append({
                    "id": segment_id,
                    "sequence": panel.get("number", 0),
                    "segment_type": panel.get("type", "panel"),
                    "description": panel.get("action", ""),
                    "characters": [(c.get("character_id") or "").replace("char_", "") for c in panel.get("characters", [])],
                    "dialogues": dialogues,
                    "narration": None,
                    "sfx": " ".join(panel.get("sfx", [])) if panel.get("sfx") else None,
                    "shot_type": panel.get("composition", {}).get("shot_type", ""),
                    "mood": "",
                    "scroll_pacing": "normal",
                    "height_hint": "standard"
                })

            scenes.append({
                "id": scene["id"],
                "title": scene.get("description", f"Scene {scene.get('number', '')}"),
                "segments": segments
            })

        chapters.append({
            "title": chapter.get("title", f"Chapter {chapter.get('number', '')}"),
            "summary": chapter.get("summary", ""),
            "scenes": scenes
        })

    return {
        "title": story.get("title", project_data.get("name", "")),
        "description": story.get("synopsis", ""),
        "premise": story.get("logline", ""),
        "genre": story.get("genre", ""),
        "tags": story.get("themes", []),
        "style": {
            "tone": story.get("tone", ""),
            "target_audience": story.get("target_audience", "")
        },
        "characters": characters,
        "chapters": chapters
    }


def upload_to_r2(local_path: str, r2_path: str):
    """Upload a file to R2 bucket using S3 API."""
    s3 = get_s3_client()

    # Determine content type
    content_type, _ = mimetypes.guess_type(local_path)
    if content_type is None:
        if r2_path.endswith(".json"):
            content_type = "application/json"
        elif r2_path.endswith(".png"):
            content_type = "image/png"
        elif r2_path.endswith(".jpg") or r2_path.endswith(".jpeg"):
            content_type = "image/jpeg"
        else:
            content_type = "application/octet-stream"

    try:
        with open(local_path, "rb") as f:
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=r2_path,
                Body=f,
                ContentType=content_type,
            )
        print(f"  Uploaded: {r2_path}")
    except Exception as e:
        print(f"  Error uploading {r2_path}: {e}")


def upload_project(project_dir: Path):
    """Upload a single project to R2."""
    project_name = project_dir.name
    project_json_path = project_dir / "project.json"

    if not project_json_path.exists():
        print(f"Skipping {project_name}: no project.json")
        return

    print(f"\nProcessing: {project_name}")

    # Load and transform project.json
    with open(project_json_path) as f:
        project_data = json.load(f)

    webtoon_data = transform_project_to_webtoon(project_data)

    # Write transformed webtoon.json to temp file and upload
    temp_webtoon_path = project_dir / "webtoon.json"
    with open(temp_webtoon_path, "w") as f:
        json.dump(webtoon_data, f, indent=2)

    upload_to_r2(str(temp_webtoon_path), f"{project_name}/webtoon.json")

    # Build character ID mapping from project data (folder name -> character id)
    char_id_map = {}
    for char in project_data.get("characters", []):
        # char["id"] is like "char_ember_formerly_ignis"
        # The folder name is like "ember-formerly-ignis"
        char_id = char["id"].replace("char_", "")  # ember_formerly_ignis
        folder_name = char_id.replace("_", "-")     # ember-formerly-ignis
        char_id_map[folder_name] = char_id

    # Upload character portraits
    characters_dir = project_dir / "assets" / "characters"
    if characters_dir.exists():
        for char_dir in characters_dir.iterdir():
            if char_dir.is_dir() and not char_dir.name.startswith("."):
                # Use character ID (with underscores) for R2 path
                char_id = char_id_map.get(char_dir.name, char_dir.name)

                portrait_path = char_dir / "portrait.png"
                if portrait_path.exists():
                    r2_path = f"{project_name}/assets/characters/{char_id}_portrait.png"
                    upload_to_r2(str(portrait_path), r2_path)

                sheet_path = char_dir / "sheet.png"
                if sheet_path.exists():
                    r2_path = f"{project_name}/assets/characters/{char_id}.png"
                    upload_to_r2(str(sheet_path), r2_path)

    # Upload panels as chapter assets
    panels_dir = project_dir / "assets" / "panels"
    if panels_dir.exists():
        for chapter_dir in panels_dir.iterdir():
            if chapter_dir.is_dir() and chapter_dir.name.startswith("chapter-"):
                chapter_num = chapter_dir.name.replace("chapter-", "")
                for scene_dir in chapter_dir.iterdir():
                    if scene_dir.is_dir() and scene_dir.name.startswith("scene-"):
                        scene_num = scene_dir.name.replace("scene-", "")
                        for panel_file in scene_dir.glob("panel-*.png"):
                            if ".backup" not in str(panel_file):
                                panel_num = panel_file.stem.replace("panel-", "")
                                segment_id = f"ch{chapter_num}_s{scene_num}_p{panel_num}"
                                # Keep original extension
                                ext = panel_file.suffix.lower()
                                r2_path = f"{project_name}/assets/chapters/ch{chapter_num}/{segment_id}{ext}"
                                upload_to_r2(str(panel_file), r2_path)

    # Upload cover if exists (use main character portrait as fallback)
    covers_dir = project_dir / "assets" / "covers"
    if covers_dir.exists():
        for cover_file in covers_dir.glob("*"):
            if cover_file.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                upload_to_r2(str(cover_file), f"{project_name}/assets/covers/series_cover.jpg")
                break
    else:
        # Use main character (protagonist) portrait as cover fallback
        if characters_dir.exists():
            # Find protagonist first
            protagonist_folder = None
            fallback_folder = None
            for char in project_data.get("characters", []):
                if char.get("role") == "protagonist":
                    # Convert char ID to folder name (char_hao -> hao)
                    char_id = char["id"].replace("char_", "")
                    protagonist_folder = char_id.replace("_", "-")
                    break

            # Try protagonist first, then fall back to first character
            for char_dir in characters_dir.iterdir():
                if char_dir.is_dir() and not char_dir.name.startswith("."):
                    if fallback_folder is None:
                        fallback_folder = char_dir.name
                    if protagonist_folder and char_dir.name == protagonist_folder:
                        portrait = char_dir / "portrait.png"
                        if portrait.exists():
                            upload_to_r2(str(portrait), f"{project_name}/assets/covers/series_cover.jpg")
                            break
            else:
                # No protagonist found, use fallback
                if fallback_folder:
                    portrait = characters_dir / fallback_folder / "portrait.png"
                    if portrait.exists():
                        upload_to_r2(str(portrait), f"{project_name}/assets/covers/series_cover.jpg")


def list_available_projects() -> list[str]:
    """List all available project names."""
    projects = []
    for project_dir in PROJECTS_DIR.iterdir():
        if project_dir.is_dir() and not project_dir.name.startswith("."):
            if (project_dir / "project.json").exists():
                projects.append(project_dir.name)
    return sorted(projects)


def main():
    parser = argparse.ArgumentParser(
        description="Upload dreamwright projects to R2 bucket for webtoon showcase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                        Upload all projects
    %(prog)s dragon-mishap          Upload specific project
    %(prog)s dragon-mishap the-last-hunter  Upload multiple projects
    %(prog)s --list                 List available projects
        """
    )
    parser.add_argument(
        "projects",
        nargs="*",
        help="Project name(s) to upload. If not specified, uploads all projects."
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available projects and exit"
    )
    args = parser.parse_args()

    # List projects and exit
    if args.list:
        available = list_available_projects()
        print("Available projects:")
        for p in available:
            print(f"  - {p}")
        return

    # Determine which projects to upload
    if args.projects:
        # Validate specified projects exist
        available = set(list_available_projects())
        project_names = []
        for name in args.projects:
            if name not in available:
                print(f"Error: Project '{name}' not found in {PROJECTS_DIR}")
                print(f"Available projects: {', '.join(sorted(available))}")
                sys.exit(1)
            project_names.append(name)
    else:
        # Upload all projects
        project_names = list_available_projects()

    if not project_names:
        print("No projects found to upload.")
        return

    print(f"Uploading {len(project_names)} project(s) to R2 bucket '{BUCKET_NAME}'")

    for name in project_names:
        project_dir = PROJECTS_DIR / name
        upload_project(project_dir)

    print("\nDone!")


if __name__ == "__main__":
    main()
