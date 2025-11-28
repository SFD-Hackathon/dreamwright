#!/usr/bin/env python3
"""
Local web server for viewing DreamWright webtoon projects with vertical scroll format.
"""

import argparse
import html as html_escape
import http.server
import json
import mimetypes
import os
import re
import socketserver
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

DEFAULT_PORT = 8000
PROJECTS_DIR = Path("projects")

# Safe project ID pattern (alphanumeric, hyphens, underscores only)
SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def escape(text: str) -> str:
    """Safely escape text for HTML output."""
    if text is None:
        return ""
    return html_escape.escape(str(text))


def slugify(text: str) -> str:
    """Convert text to a URL/filename-friendly slug.

    Args:
        text: Text to slugify

    Returns:
        Slugified text (lowercase, hyphens instead of spaces)
    """
    # Convert to lowercase
    text = text.lower()
    # Replace spaces and underscores with hyphens
    text = re.sub(r'[\s_]+', '-', text)
    # Remove any characters that aren't alphanumeric or hyphens
    text = re.sub(r'[^\w\-]', '', text)
    # Remove multiple consecutive hyphens
    text = re.sub(r'-+', '-', text)
    # Strip leading/trailing hyphens
    text = text.strip('-')
    return text


def validate_project_id(project_id: str) -> bool:
    """Validate project ID to prevent path traversal."""
    if not project_id or not SAFE_ID_PATTERN.match(project_id):
        return False
    # Extra check: ensure no path separators
    if "/" in project_id or "\\" in project_id or ".." in project_id:
        return False
    return True


def safe_project_path(project_id: str) -> Path | None:
    """Get validated project path, returns None if invalid."""
    if not validate_project_id(project_id):
        return None
    project_path = (PROJECTS_DIR / project_id).resolve()
    # Ensure path is under PROJECTS_DIR
    try:
        project_path.relative_to(PROJECTS_DIR.resolve())
    except ValueError:
        return None
    return project_path


class WebtoonHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler for serving webtoon content."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        # Check for debug mode in query params
        debug_mode = query.get("debug", ["0"])[0] == "1"

        try:
            if path == "/" or path == "":
                self.send_index()
            elif path.startswith("/project/") and "/chapter" not in path:
                # /project/{project_id} - cover page
                parts = path.split("/")
                if len(parts) >= 3:
                    project_id = parts[2]
                    if not validate_project_id(project_id):
                        self.send_error(400, "Invalid project ID")
                        return
                    self.send_project_cover(project_id)
                else:
                    self.send_error(404, "Project not found")
            elif path.startswith("/view/"):
                # /view/{project_id}/chapter/{N}
                parts = path.split("/")
                if len(parts) >= 5 and parts[3] == "chapter":
                    project_id = parts[2]
                    if not validate_project_id(project_id):
                        self.send_error(400, "Invalid project ID")
                        return
                    try:
                        chapter_num = int(parts[4])
                    except ValueError:
                        self.send_error(400, "Invalid chapter number")
                        return
                    self.send_chapter_viewer(project_id, chapter_num, debug_mode)
                else:
                    self.send_error(404, "Chapter not found")
            elif path.startswith("/api/projects"):
                self.send_projects_list()
            elif path.startswith("/api/project/"):
                parts = path.split("/")
                if len(parts) < 4:
                    self.send_error(400, "Invalid API request")
                    return
                project_id = parts[3]
                if not validate_project_id(project_id):
                    self.send_error(400, "Invalid project ID")
                    return
                self.send_project_data(project_id)
            elif path.startswith("/projects/"):
                # Serve static files from projects directory only
                self.serve_project_asset(path)
            else:
                # Block all other paths - don't serve arbitrary files
                self.send_error(404, "Not found")
        except Exception as e:
            self.send_error(500, f"Server error: {type(e).__name__}")

    def serve_project_asset(self, path: str):
        """Serve static assets from projects directory with path validation."""
        # Remove leading /projects/
        relative_path = path[10:]  # len("/projects/") = 10

        # Validate and resolve path
        try:
            full_path = (PROJECTS_DIR / relative_path).resolve()
            # Ensure path is under PROJECTS_DIR
            full_path.relative_to(PROJECTS_DIR.resolve())
        except (ValueError, RuntimeError):
            self.send_error(403, "Access denied")
            return

        if not full_path.exists() or not full_path.is_file():
            self.send_error(404, "File not found")
            return

        # Serve the file
        content_type, _ = mimetypes.guess_type(str(full_path))
        content_type = content_type or "application/octet-stream"

        try:
            with open(full_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        except IOError:
            self.send_error(500, "Error reading file")

    def load_project(self, project_id: str) -> dict | None:
        """Load project data from project.json with error handling."""
        project_path = safe_project_path(project_id)
        if not project_path:
            return None
        project_json = project_path / "project.json"
        if not project_json.exists():
            return None
        try:
            return json.loads(project_json.read_text())
        except (json.JSONDecodeError, IOError):
            return None

    def send_index(self):
        """Send the main index page listing all projects."""
        projects = []
        if PROJECTS_DIR.exists():
            for project_dir in PROJECTS_DIR.iterdir():
                if project_dir.is_dir():
                    project_json = project_dir / "project.json"
                    if project_json.exists():
                        data = json.loads(project_json.read_text())
                        story = data.get("story", {})
                        chapters = data.get("chapters", [])
                        total_panels = sum(
                            sum(len(scene.get("panels", [])) for scene in ch.get("scenes", []))
                            for ch in chapters
                        )
                        projects.append(
                            {
                                "id": project_dir.name,
                                "name": data.get("name", project_dir.name),
                                "title": story.get("title", "Untitled"),
                                "logline": story.get("logline", ""),
                                "genre": story.get("genre", ""),
                                "chapters": len(chapters),
                                "panels": total_panels,
                                "characters": len(data.get("characters", [])),
                            }
                        )

        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DreamWright Viewer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }
        h1 { text-align: center; margin-bottom: 30px; color: #fff; }
        .projects { max-width: 900px; margin: 0 auto; }
        .project {
            display: block;
            background: #16213e;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            text-decoration: none;
            color: #fff;
            border: 1px solid transparent;
            transition: border-color 0.2s, transform 0.2s;
        }
        .project:hover { border-color: #e94560; transform: translateX(5px); }
        .project h2 { color: #e94560; margin-bottom: 8px; font-size: 1.5rem; }
        .project .genre {
            display: inline-block;
            background: #e94560;
            color: #fff;
            padding: 4px 12px;
            border-radius: 15px;
            font-size: 11px;
            text-transform: uppercase;
            margin-bottom: 10px;
        }
        .project .logline { color: #aaa; margin-bottom: 15px; font-style: italic; line-height: 1.5; }
        .project .stats { display: flex; gap: 20px; flex-wrap: wrap; }
        .project .stat {
            background: #0f3460;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
        }
        .project .stat strong { color: #e94560; }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #666;
        }
        .empty-state h2 { color: #888; margin-bottom: 15px; }
    </style>
</head>
<body>
    <h1>DreamWright Viewer</h1>
    <div class="projects">
"""
        if projects:
            for p in projects:
                logline = escape(p['logline'][:200]) + ('...' if len(p['logline']) > 200 else '')
                html += f"""
        <a href="/project/{escape(p['id'])}" class="project">
            <span class="genre">{escape(p['genre'])}</span>
            <h2>{escape(p['title'])}</h2>
            <p class="logline">{logline}</p>
            <div class="stats">
                <span class="stat"><strong>{p['chapters']}</strong> chapters</span>
                <span class="stat"><strong>{p['panels']}</strong> panels</span>
                <span class="stat"><strong>{p['characters']}</strong> characters</span>
            </div>
        </a>
"""
        else:
            html += """
        <div class="empty-state">
            <h2>No projects found</h2>
            <p>Create a project with: dreamwright init my-project</p>
        </div>
"""

        html += """
    </div>
</body>
</html>
"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def send_project_cover(self, project_id: str):
        """Send the project cover/introduction page."""
        data = self.load_project(project_id)
        if not data:
            self.send_error(404, "Project not found")
            return

        story = data.get("story", {})
        characters = data.get("characters", [])
        locations = data.get("locations", [])
        chapters = data.get("chapters", [])

        # Build chapter stats
        chapter_stats = []
        total_panels = 0
        for ch in chapters:
            panel_count = sum(len(scene.get("panels", [])) for scene in ch.get("scenes", []))
            total_panels += panel_count
            chapter_stats.append(
                {
                    "number": ch.get("number", 0),
                    "title": ch.get("title", "Untitled"),
                    "summary": ch.get("summary", ""),
                    "scenes": len(ch.get("scenes", [])),
                    "panels": panel_count,
                }
            )

        # Get first character portrait as cover
        cover_img = ""
        if characters:
            first_char = characters[0]
            char_name = slugify(first_char.get("name", ""))
            portrait_path = PROJECTS_DIR / project_id / "assets" / "characters" / char_name / "portrait.png"
            if portrait_path.exists():
                cover_img = f"/projects/{project_id}/assets/characters/{char_name}/portrait.png"

        main_chars = [c for c in characters if c.get("role") == "protagonist"]
        supporting_chars = [c for c in characters if c.get("role") != "protagonist"]

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{story.get('title', 'Project')} - DreamWright</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
            color: #fff;
            min-height: 100vh;
        }}
        .back-link {{
            position: fixed;
            top: 20px;
            left: 20px;
            color: #e94560;
            text-decoration: none;
            font-size: 14px;
            z-index: 100;
            background: rgba(0,0,0,0.5);
            padding: 8px 16px;
            border-radius: 20px;
            transition: background 0.2s;
        }}
        .back-link:hover {{ background: rgba(233,69,96,0.3); }}

        .hero {{
            position: relative;
            min-height: 70vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }}
        .hero-bg {{
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background-size: cover;
            background-position: center;
            filter: blur(20px) brightness(0.4);
            transform: scale(1.1);
        }}
        .hero-content {{
            position: relative;
            z-index: 1;
            display: flex;
            gap: 50px;
            max-width: 1200px;
            padding: 40px;
            align-items: center;
        }}
        .cover-image {{
            width: 300px;
            height: 450px;
            border-radius: 12px;
            object-fit: cover;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            border: 3px solid rgba(255,255,255,0.1);
            background: linear-gradient(135deg, #e94560, #ff6b8a);
        }}
        .hero-info {{ max-width: 600px; }}
        .hero-info h1 {{
            font-family: 'Playfair Display', serif;
            font-size: 3rem;
            font-weight: 700;
            margin-bottom: 15px;
            line-height: 1.1;
        }}
        .genre-tag {{
            display: inline-block;
            background: #e94560;
            color: #fff;
            padding: 6px 16px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 20px;
        }}
        .logline {{
            font-size: 1.1rem;
            line-height: 1.7;
            color: rgba(255,255,255,0.85);
            margin-bottom: 25px;
        }}
        .stats {{
            display: flex;
            gap: 30px;
            margin-bottom: 25px;
        }}
        .stat {{ text-align: center; }}
        .stat-value {{
            font-size: 2rem;
            font-weight: 700;
            color: #e94560;
        }}
        .stat-label {{
            font-size: 12px;
            color: rgba(255,255,255,0.6);
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .start-btn {{
            display: inline-block;
            background: linear-gradient(135deg, #e94560, #ff6b8a);
            color: #fff;
            padding: 15px 40px;
            border-radius: 30px;
            text-decoration: none;
            font-weight: 600;
            font-size: 16px;
            margin-top: 20px;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 10px 30px rgba(233,69,96,0.4);
        }}
        .start-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 15px 40px rgba(233,69,96,0.5);
        }}

        .content {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 60px 40px;
        }}
        .section {{ margin-bottom: 60px; }}
        .section-title {{
            font-family: 'Playfair Display', serif;
            font-size: 2rem;
            margin-bottom: 30px;
            padding-bottom: 15px;
            border-bottom: 2px solid rgba(255,255,255,0.1);
        }}

        .characters-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 25px;
        }}
        .character-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
            cursor: pointer;
        }}
        .character-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 15px 40px rgba(0,0,0,0.3);
        }}

        /* Modal styles */
        .modal-overlay {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            z-index: 1000;
            overflow-y: auto;
            padding: 40px 20px;
        }}
        .modal-overlay.active {{
            display: flex;
            justify-content: center;
            align-items: flex-start;
        }}
        .modal-content {{
            background: #1a1a2e;
            border-radius: 20px;
            max-width: 900px;
            width: 100%;
            padding: 30px;
            position: relative;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .modal-close {{
            position: absolute;
            top: 15px;
            right: 20px;
            font-size: 30px;
            color: #fff;
            cursor: pointer;
            opacity: 0.7;
            transition: opacity 0.2s;
        }}
        .modal-close:hover {{
            opacity: 1;
        }}
        .modal-title {{
            font-family: 'Playfair Display', serif;
            font-size: 2rem;
            margin-bottom: 10px;
        }}
        .modal-subtitle {{
            color: #e94560;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 12px;
            margin-bottom: 20px;
        }}
        .modal-images {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 25px;
        }}
        .modal-image-container {{
            text-align: center;
        }}
        .modal-image-container img {{
            max-width: 100%;
            max-height: 400px;
            border-radius: 12px;
            object-fit: contain;
            background: rgba(0,0,0,0.3);
        }}
        .modal-image-label {{
            margin-top: 10px;
            font-size: 12px;
            color: rgba(255,255,255,0.6);
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .modal-section {{
            margin-bottom: 20px;
        }}
        .modal-section-title {{
            font-size: 14px;
            color: #e94560;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }}
        .modal-section-content {{
            color: rgba(255,255,255,0.8);
            line-height: 1.6;
        }}
        .modal-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .modal-tag {{
            background: rgba(233,69,96,0.2);
            color: #e94560;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
        }}
        .json-view-btn {{
            background: #238636;
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            margin-bottom: 10px;
        }}
        .json-view-btn:hover {{
            background: #2ea043;
        }}
        .json-preview {{
            background: #0d1117;
            color: #c9d1d9;
            padding: 15px;
            border-radius: 8px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            line-height: 1.5;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 300px;
            overflow-y: auto;
            margin-top: 10px;
        }}
        .json-tabs {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .json-tab-btn {{
            background: #21262d;
            color: #8b949e;
            border: 1px solid #30363d;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 11px;
            transition: all 0.2s;
        }}
        .json-tab-btn:hover {{
            background: #30363d;
            color: #c9d1d9;
        }}
        .json-tab-btn.active {{
            background: #238636;
            color: #fff;
            border-color: #238636;
        }}
        .character-card.protagonist {{ border-color: #e94560; }}
        .character-img {{
            width: 100%;
            height: 500px;
            object-fit: cover;
            background: rgba(0,0,0,0.3);
        }}
        .character-info {{ padding: 20px; }}
        .character-name {{
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 5px;
        }}
        .character-role {{
            font-size: 12px;
            color: #e94560;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }}
        .character-desc {{
            font-size: 13px;
            color: rgba(255,255,255,0.7);
            line-height: 1.5;
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}

        .chapters-list {{
            display: flex;
            flex-direction: column;
            gap: 15px;
        }}
        .chapter-card {{
            display: flex;
            align-items: center;
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px 25px;
            text-decoration: none;
            color: #fff;
            border: 1px solid rgba(255,255,255,0.1);
            transition: all 0.2s;
        }}
        .chapter-card:hover {{
            background: rgba(233,69,96,0.2);
            border-color: #e94560;
            transform: translateX(10px);
        }}
        .chapter-num {{
            font-size: 2rem;
            font-weight: 700;
            color: #e94560;
            min-width: 80px;
        }}
        .chapter-details {{ flex: 1; }}
        .chapter-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 5px;
        }}
        .chapter-summary {{
            font-size: 13px;
            color: rgba(255,255,255,0.6);
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        .chapter-stats {{
            font-size: 12px;
            color: rgba(255,255,255,0.5);
            min-width: 120px;
            text-align: right;
        }}

        .locations-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
        }}
        .location-card {{
            position: relative;
            height: 200px;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .location-card:hover {{
            transform: scale(1.02);
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }}
        .location-card img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}
        .location-overlay {{
            position: absolute;
            bottom: 0; left: 0; right: 0;
            padding: 20px;
            background: linear-gradient(transparent, rgba(0,0,0,0.9));
        }}
        .location-name {{
            font-size: 1.1rem;
            font-weight: 600;
        }}
        .location-type {{
            font-size: 12px;
            color: rgba(255,255,255,0.6);
        }}

        @media (max-width: 768px) {{
            .hero-content {{
                flex-direction: column;
                text-align: center;
                padding: 20px;
            }}
            .cover-image {{ width: 200px; height: 300px; }}
            .hero-info h1 {{ font-size: 2rem; }}
            .stats {{ justify-content: center; }}
        }}
    </style>
</head>
<body>
    <a href="/" class="back-link">&larr; All Projects</a>

    <div class="hero">
        <div class="hero-bg" style="background-image: url('{cover_img}');"></div>
        <div class="hero-content">
            <img src="{cover_img}" alt="{escape(story.get('title', ''))}" class="cover-image" onerror="this.style.background='linear-gradient(135deg, #e94560, #ff6b8a)'">
            <div class="hero-info">
                <span class="genre-tag">{escape(story.get('genre', 'drama'))}</span>
                <h1>{escape(story.get('title', 'Untitled'))}</h1>
                <p class="logline">{escape(story.get('logline', ''))}</p>
                <div class="stats">
                    <div class="stat">
                        <div class="stat-value">{len(chapters)}</div>
                        <div class="stat-label">Chapters</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value">{total_panels}</div>
                        <div class="stat-label">Panels</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value">{len(characters)}</div>
                        <div class="stat-label">Characters</div>
                    </div>
                </div>
                <a href="/view/{project_id}/chapter/1" class="start-btn">Start Reading</a>
            </div>
        </div>
    </div>

    <div class="content">
        <div class="section">
            <h2 class="section-title">Characters</h2>
            <div class="characters-grid">
"""
        for char in main_chars + supporting_chars:
            char_name = char.get("name", "")
            char_slug = slugify(char_name)
            char_img = f"/projects/{project_id}/assets/characters/{char_slug}/portrait.png"
            char_sheet = f"/projects/{project_id}/assets/characters/{char_slug}/sheet.png"
            role = char.get("role", "supporting")
            role_class = "protagonist" if role == "protagonist" else ""
            desc = char.get("description", {})
            physical = desc.get("physical", "") if isinstance(desc, dict) else ""
            personality = desc.get("personality", "") if isinstance(desc, dict) else ""
            visual_tags = char.get("visual_tags", [])

            # Encode all char data as single JSON, HTML-escaped for data attribute
            portrait_json_url = f"/projects/{project_id}/assets/characters/{char_slug}/portrait.json"
            sheet_json_url = f"/projects/{project_id}/assets/characters/{char_slug}/sheet.json"
            char_data = {
                "name": char_name,
                "role": role,
                "portrait": char_img,
                "sheet": char_sheet,
                "physical": physical,
                "personality": personality,
                "tags": visual_tags,
                "portraitJson": portrait_json_url,
                "sheetJson": sheet_json_url
            }
            char_data_json = escape(json.dumps(char_data))

            html += f"""
                <div class="character-card {role_class}" onclick="openCharacterModal(this)"
                     data-char="{char_data_json}">
                    <img src="{char_img}" alt="{escape(char_name)}" class="character-img" onerror="this.style.background='linear-gradient(135deg, #24243e, #302b63)'">
                    <div class="character-info">
                        <div class="character-role">{escape(role)}</div>
                        <div class="character-name">{escape(char_name)}</div>
                        <p class="character-desc">{escape(physical[:150])}</p>
                    </div>
                </div>
"""

        html += """
            </div>
        </div>

        <div class="section">
            <h2 class="section-title">Chapters</h2>
            <div class="chapters-list">
"""
        for ch in chapter_stats:
            ch_summary = escape(ch['summary'][:100]) + '...'
            html += f"""
                <a href="/view/{escape(project_id)}/chapter/{ch['number']}" class="chapter-card">
                    <div class="chapter-num">{ch['number']}</div>
                    <div class="chapter-details">
                        <div class="chapter-title">{escape(ch['title'])}</div>
                        <div class="chapter-summary">{ch_summary}</div>
                    </div>
                    <div class="chapter-stats">{ch['scenes']} scenes, {ch['panels']} panels</div>
                </a>
"""

        html += """
            </div>
        </div>

        <div class="section">
            <h2 class="section-title">Locations</h2>
            <div class="locations-grid">
"""
        for loc in locations:
            loc_name = loc.get("name", "")
            loc_slug = slugify(loc_name)
            loc_img = f"/projects/{project_id}/assets/locations/{loc_slug}/reference.png"
            loc_type = loc.get("type", "interior")
            loc_desc = loc.get("description", "")
            loc_visual_tags = loc.get("visual_tags", [])

            # Encode all location data as single JSON
            loc_ref_json_url = f"/projects/{project_id}/assets/locations/{loc_slug}/reference.json"
            loc_data = {
                "name": loc_name,
                "type": loc_type,
                "image": loc_img,
                "description": loc_desc,
                "tags": loc_visual_tags,
                "referenceJson": loc_ref_json_url
            }
            loc_data_json = escape(json.dumps(loc_data))

            html += f"""
                <div class="location-card" onclick="openLocationModal(this)"
                     data-loc="{loc_data_json}">
                    <img src="{loc_img}" alt="{escape(loc_name)}" onerror="this.style.background='linear-gradient(135deg, #24243e, #302b63)'">
                    <div class="location-overlay">
                        <div class="location-name">{escape(loc_name)}</div>
                        <div class="location-type">{escape(loc_type)}</div>
                    </div>
                </div>
"""

        html += """
            </div>
        </div>
    </div>

    <!-- Modal for character/location details -->
    <div id="detailModal" class="modal-overlay" onclick="if(event.target === this) closeModal()">
        <div class="modal-content">
            <span class="modal-close" onclick="closeModal()">&times;</span>
            <div id="modalBody"></div>
        </div>
    </div>

    <script>
    let charMetadataCache = {};

    function openCharacterModal(el) {
        const data = JSON.parse(el.dataset.char);
        const { name, role, portrait, sheet, physical, personality, tags, portraitJson, sheetJson } = data;

        let tagsHtml = '';
        if (tags && tags.length > 0) {
            tagsHtml = '<div class="modal-section"><div class="modal-section-title">Visual Tags</div><div class="modal-tags">' +
                tags.map(t => '<span class="modal-tag">' + t + '</span>').join('') + '</div></div>';
        }

        // Store URLs for async loading
        charMetadataCache = { portraitJson, sheetJson, portrait: null, sheet: null };

        const html = `
            <div class="modal-title">${name}</div>
            <div class="modal-subtitle">${role}</div>
            <div class="modal-images">
                <div class="modal-image-container">
                    <img src="${portrait}" alt="Portrait" onerror="this.parentElement.style.display='none'">
                    <div class="modal-image-label">Portrait</div>
                </div>
                <div class="modal-image-container">
                    <img src="${sheet}" alt="Character Sheet" onerror="this.parentElement.style.display='none'">
                    <div class="modal-image-label">Character Sheet</div>
                </div>
            </div>
            ${physical ? '<div class="modal-section"><div class="modal-section-title">Physical Description</div><div class="modal-section-content">' + physical + '</div></div>' : ''}
            ${personality ? '<div class="modal-section"><div class="modal-section-title">Personality</div><div class="modal-section-content">' + personality + '</div></div>' : ''}
            ${tagsHtml}
            <div class="modal-section">
                <div class="modal-section-title">Generation Metadata</div>
                <div class="json-tabs">
                    <button class="json-tab-btn active" onclick="showCharTab('charData')">Character Data</button>
                    <button class="json-tab-btn" onclick="showCharTab('portraitMeta')">Portrait JSON</button>
                    <button class="json-tab-btn" onclick="showCharTab('sheetMeta')">Sheet JSON</button>
                </div>
                <pre id="charJsonContent" class="json-preview">${JSON.stringify(data, null, 2)}</pre>
            </div>
        `;

        document.getElementById('modalBody').innerHTML = html;
        document.getElementById('detailModal').classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    async function showCharTab(tab) {
        document.querySelectorAll('.json-tab-btn').forEach(b => b.classList.remove('active'));
        event.target.classList.add('active');
        const content = document.getElementById('charJsonContent');

        if (tab === 'charData') {
            content.textContent = JSON.stringify(charMetadataCache, null, 2);
        } else if (tab === 'portraitMeta') {
            if (!charMetadataCache.portrait) {
                try {
                    const resp = await fetch(charMetadataCache.portraitJson);
                    charMetadataCache.portrait = resp.ok ? await resp.text() : '{"error": "File not found"}';
                } catch { charMetadataCache.portrait = '{"error": "Failed to load"}'; }
            }
            try {
                content.textContent = JSON.stringify(JSON.parse(charMetadataCache.portrait), null, 2);
            } catch { content.textContent = charMetadataCache.portrait; }
        } else if (tab === 'sheetMeta') {
            if (!charMetadataCache.sheet) {
                try {
                    const resp = await fetch(charMetadataCache.sheetJson);
                    charMetadataCache.sheet = resp.ok ? await resp.text() : '{"error": "File not found"}';
                } catch { charMetadataCache.sheet = '{"error": "Failed to load"}'; }
            }
            try {
                content.textContent = JSON.stringify(JSON.parse(charMetadataCache.sheet), null, 2);
            } catch { content.textContent = charMetadataCache.sheet; }
        }
    }

    let locMetadataCache = {};

    function openLocationModal(el) {
        const data = JSON.parse(el.dataset.loc);
        const { name, type, image, description, tags, referenceJson } = data;

        let tagsHtml = '';
        if (tags && tags.length > 0) {
            tagsHtml = '<div class="modal-section"><div class="modal-section-title">Visual Tags</div><div class="modal-tags">' +
                tags.map(t => '<span class="modal-tag">' + t + '</span>').join('') + '</div></div>';
        }

        // Store URL for async loading
        locMetadataCache = { referenceJson, reference: null, data: data };

        const html = `
            <div class="modal-title">${name}</div>
            <div class="modal-subtitle">${type}</div>
            <div class="modal-images">
                <div class="modal-image-container">
                    <img src="${image}" alt="Location Reference" onerror="this.parentElement.style.display='none'">
                    <div class="modal-image-label">Reference Image</div>
                </div>
            </div>
            ${description ? '<div class="modal-section"><div class="modal-section-title">Description</div><div class="modal-section-content">' + description + '</div></div>' : ''}
            ${tagsHtml}
            <div class="modal-section">
                <div class="modal-section-title">Generation Metadata</div>
                <div class="json-tabs">
                    <button class="json-tab-btn active" onclick="showLocTab('locData')">Location Data</button>
                    <button class="json-tab-btn" onclick="showLocTab('refMeta')">Reference JSON</button>
                </div>
                <pre id="locJsonContent" class="json-preview">${JSON.stringify(data, null, 2)}</pre>
            </div>
        `;

        document.getElementById('modalBody').innerHTML = html;
        document.getElementById('detailModal').classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    async function showLocTab(tab) {
        document.querySelectorAll('.json-tab-btn').forEach(b => b.classList.remove('active'));
        event.target.classList.add('active');
        const content = document.getElementById('locJsonContent');

        if (tab === 'locData') {
            content.textContent = JSON.stringify(locMetadataCache.data, null, 2);
        } else if (tab === 'refMeta') {
            if (!locMetadataCache.reference) {
                try {
                    const resp = await fetch(locMetadataCache.referenceJson);
                    locMetadataCache.reference = resp.ok ? await resp.text() : '{"error": "File not found"}';
                } catch { locMetadataCache.reference = '{"error": "Failed to load"}'; }
            }
            try {
                content.textContent = JSON.stringify(JSON.parse(locMetadataCache.reference), null, 2);
            } catch { content.textContent = locMetadataCache.reference; }
        }
    }

    function closeModal() {
        document.getElementById('detailModal').classList.remove('active');
        document.body.style.overflow = '';
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeModal();
    });
    </script>
</body>
</html>
"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def send_chapter_viewer(self, project_id: str, chapter_num: int, debug_mode: bool = False):
        """Send the chapter viewer page with vertical scroll."""
        data = self.load_project(project_id)
        if not data:
            self.send_error(404, "Project not found")
            return

        story = data.get("story", {})
        characters = data.get("characters", [])
        chapters = data.get("chapters", [])

        # Find chapter
        chapter = None
        for ch in chapters:
            if ch.get("number") == chapter_num:
                chapter = ch
                break

        if not chapter:
            self.send_error(404, "Chapter not found")
            return

        # Build character lookup
        char_lookup = {c.get("id"): c for c in characters}

        # Collect all panels from scenes
        panels = []
        for scene in chapter.get("scenes", []):
            scene_num = scene.get("number", 0)
            for panel in scene.get("panels", []):
                panel_num = panel.get("number", 0)
                panel_path = (
                    PROJECTS_DIR
                    / project_id
                    / "assets"
                    / "panels"
                    / f"chapter-{chapter_num}"
                    / f"scene-{scene_num}"
                    / f"panel-{panel_num}.png"
                )
                panels.append(
                    {
                        "scene_num": scene_num,
                        "panel_num": panel_num,
                        "panel": panel,
                        "scene": scene,
                        "exists": panel_path.exists(),
                        "url": f"/projects/{project_id}/assets/panels/chapter-{chapter_num}/scene-{scene_num}/panel-{panel_num}.png",
                    }
                )

        debug_toggle_url = f"/view/{project_id}/chapter/{chapter_num}{'?debug=1' if not debug_mode else ''}"
        debug_toggle_text = "Debug: OFF" if not debug_mode else "Debug: ON"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>{escape(story.get('title', 'Project'))} - Ch.{chapter_num}: {escape(chapter.get('title', ''))}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Comic+Neue:wght@400;700&family=Bangers&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #0a0a0f;
            min-height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        .header {{
            position: fixed;
            top: 0; left: 0; right: 0;
            background: rgba(0,0,0,0.95);
            color: #fff;
            padding: 10px 15px;
            z-index: 100;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #222;
        }}
        .header a {{ color: #e94560; text-decoration: none; }}
        .header h1 {{ font-size: 16px; }}
        .debug-toggle {{
            background: {'#e94560' if debug_mode else '#333'};
            color: #fff;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
            transition: background 0.2s;
        }}
        .debug-toggle:hover {{ background: {'#ff6b8a' if debug_mode else '#555'}; }}

        .chapter-container {{
            max-width: {'1400px' if debug_mode else '800px'};
            margin: 0 auto;
            padding-top: 50px;
        }}

        .panel-row {{
            display: {'flex' if debug_mode else 'block'};
            gap: 0;
            margin-bottom: {'2px' if debug_mode else '0'};
            background: {'#12121a' if debug_mode else 'transparent'};
        }}

        .debug-left {{
            display: {'block' if debug_mode else 'none'};
            width: 250px;
            flex-shrink: 0;
            background: #0d1117;
            border-right: 1px solid #333;
            padding: 10px;
            font-size: 11px;
            color: #888;
            font-family: 'JetBrains Mono', monospace;
        }}
        .debug-left .section-title {{
            color: #58a6ff;
            font-weight: 600;
            margin-bottom: 6px;
            text-transform: uppercase;
            font-size: 10px;
        }}
        .debug-left .info-block {{
            margin-bottom: 12px;
            padding-bottom: 10px;
            border-bottom: 1px solid #222;
        }}
        .debug-left .info-row {{
            display: flex;
            margin-bottom: 3px;
        }}
        .debug-left .info-label {{
            color: #666;
            width: 70px;
            flex-shrink: 0;
        }}
        .debug-left .info-value {{
            color: #9cdcfe;
            word-break: break-word;
        }}

        .panel {{
            position: relative;
            flex: 1;
            min-width: 0;
        }}
        .panel img {{
            width: 100%;
            height: auto;
            display: block;
        }}
        .panel .placeholder {{
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            min-height: 300px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #666;
            font-size: 14px;
        }}

        /* Panel overlays for dialogue/SFX */
        .panel-overlays {{
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            pointer-events: none;
            padding: 15px;
            display: flex;
            flex-direction: column;
            justify-content: flex-end;
        }}
        .dialogue-bubble {{
            background: rgba(255,255,255,0.95);
            color: #1a1a2e;
            padding: 12px 16px;
            border-radius: 18px;
            margin-bottom: 8px;
            max-width: 80%;
            font-family: 'Comic Neue', cursive;
            font-size: 15px;
            line-height: 1.4;
            box-shadow: 0 3px 10px rgba(0,0,0,0.3);
            position: relative;
        }}
        .dialogue-bubble.thought {{
            background: rgba(255,255,255,0.85);
            border-radius: 50px;
            font-style: italic;
        }}
        .dialogue-bubble.thought::before {{
            content: '💭';
            position: absolute;
            top: -8px;
            left: 10px;
            font-size: 16px;
        }}
        .dialogue-bubble.narration {{
            background: rgba(0,0,0,0.8);
            color: #fff;
            font-style: italic;
            border-radius: 4px;
            max-width: 100%;
            text-align: center;
        }}
        .dialogue-bubble .speaker {{
            font-weight: 700;
            font-size: 12px;
            color: #e94560;
            margin-bottom: 4px;
            text-transform: uppercase;
        }}
        .dialogue-bubble.narration .speaker {{
            color: #aaa;
        }}
        .sfx-overlay {{
            position: absolute;
            top: 15px;
            right: 15px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            align-items: flex-end;
        }}
        .sfx-text {{
            font-family: 'Bangers', cursive;
            font-size: 24px;
            color: #fff;
            text-shadow: 2px 2px 0 #e94560, -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000;
            transform: rotate(-5deg);
        }}

        .debug-right {{
            display: {'flex' if debug_mode else 'none'};
            width: 60px;
            flex-shrink: 0;
            background: #0d1117;
            border-left: 1px solid #333;
            padding: 10px;
            align-items: center;
            justify-content: center;
        }}
        .inspect-btn {{
            background: #238636;
            color: #fff;
            border: none;
            padding: 10px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-family: 'JetBrains Mono', monospace;
            transition: background 0.2s;
        }}
        .inspect-btn:hover {{
            background: #2ea043;
        }}

        /* JSON Modal */
        .json-modal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            z-index: 1000;
            overflow: auto;
        }}
        .json-modal.active {{
            display: flex;
            justify-content: center;
            padding: 40px 20px;
        }}
        .json-modal-content {{
            background: #0d1117;
            border-radius: 12px;
            max-width: 1000px;
            width: 100%;
            max-height: 90vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            border: 1px solid #333;
        }}
        .json-modal-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            border-bottom: 1px solid #333;
            background: #161b22;
        }}
        .json-modal-title {{
            color: #fff;
            font-family: 'JetBrains Mono', monospace;
            font-size: 14px;
        }}
        .json-modal-close {{
            color: #fff;
            font-size: 24px;
            cursor: pointer;
            opacity: 0.7;
        }}
        .json-modal-close:hover {{
            opacity: 1;
        }}
        .json-modal-tabs {{
            display: flex;
            background: #161b22;
            border-bottom: 1px solid #333;
        }}
        .json-tab {{
            padding: 10px 20px;
            color: #8b949e;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
        }}
        .json-tab:hover {{
            color: #c9d1d9;
        }}
        .json-tab.active {{
            color: #58a6ff;
            border-bottom-color: #58a6ff;
        }}
        .json-modal-body {{
            flex: 1;
            overflow: auto;
            padding: 20px;
        }}
        .json-content {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: #c9d1d9;
            white-space: pre-wrap;
            word-break: break-word;
            line-height: 1.5;
        }}
        .json-content .key {{ color: #79c0ff; }}
        .json-content .string {{ color: #a5d6ff; }}
        .json-content .number {{ color: #79c0ff; }}
        .json-content .boolean {{ color: #ff7b72; }}
        .json-content .null {{ color: #8b949e; }}
        .debug-right .section-title {{
            color: #f97583;
            font-weight: 600;
            margin-bottom: 6px;
            text-transform: uppercase;
            font-size: 10px;
        }}
        .debug-right .action-text {{
            color: #c9d1d9;
            font-size: 12px;
            line-height: 1.5;
            margin-bottom: 10px;
            padding: 8px;
            background: #161b22;
            border-radius: 4px;
            border-left: 3px solid #e94560;
        }}
        .debug-right .chars-list {{
            margin-bottom: 10px;
        }}
        .debug-right .char-item {{
            padding: 6px 8px;
            background: #161b22;
            border-radius: 4px;
            margin-bottom: 4px;
        }}
        .debug-right .char-name {{
            color: #79c0ff;
            font-weight: 500;
        }}
        .debug-right .char-detail {{
            color: #8b949e;
            font-size: 9px;
        }}
        .debug-right .dialogue-list {{
            margin-bottom: 10px;
        }}
        .debug-right .dialogue-item {{
            padding: 8px;
            background: #161b22;
            border-radius: 4px;
            margin-bottom: 4px;
            border-left: 3px solid #58a6ff;
        }}
        .debug-right .dialogue-speaker {{
            color: #58a6ff;
            font-weight: 500;
            font-size: 11px;
            margin-bottom: 4px;
        }}
        .debug-right .dialogue-text {{
            color: #c9d1d9;
            font-size: 12px;
            line-height: 1.4;
            font-style: italic;
        }}
        .debug-right .sfx-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 10px;
        }}
        .debug-right .sfx-item {{
            background: #3d1f47;
            color: #d2a8ff;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 10px;
            font-weight: 500;
        }}

        .end-card {{
            text-align: center;
            padding: 50px 20px;
            color: #fff;
        }}
        .end-card h2 {{ margin-bottom: 20px; }}
        .end-card a {{
            display: inline-block;
            background: #e94560;
            color: #fff;
            padding: 10px 20px;
            border-radius: 8px;
            text-decoration: none;
            margin: 5px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/project/{project_id}">&larr; Back</a>
        <h1>Ch.{chapter_num}: {escape(chapter.get('title', ''))}</h1>
        <div style="display: flex; align-items: center; gap: 15px;">
            <span>{len(panels)} panels</span>
            <a href="{debug_toggle_url}" class="debug-toggle">{debug_toggle_text}</a>
        </div>
    </div>

    <div class="chapter-container">
"""

        for p in panels:
            panel = p["panel"]
            scene = p["scene"]
            composition = panel.get("composition", {})

            html += f"""
        <div class="panel-row">
"""
            # Left debug panel
            if debug_mode:
                html += f"""
            <div class="debug-left">
                <div class="info-block">
                    <div class="section-title">Scene</div>
                    <div class="info-row"><span class="info-label">number:</span><span class="info-value">{escape(str(scene.get('number', 'N/A')))}</span></div>
                    <div class="info-row"><span class="info-label">location:</span><span class="info-value">{escape(str(scene.get('location_id', 'N/A')))}</span></div>
                    <div class="info-row"><span class="info-label">time:</span><span class="info-value">{escape(str(scene.get('time_of_day', 'N/A')))}</span></div>
                </div>
                <div class="info-block">
                    <div class="section-title">Panel</div>
                    <div class="info-row"><span class="info-label">number:</span><span class="info-value">{escape(str(panel.get('number', 'N/A')))}</span></div>
                    <div class="info-row"><span class="info-label">shot:</span><span class="info-value">{escape(str(composition.get('shot_type', 'N/A')))}</span></div>
                    <div class="info-row"><span class="info-label">angle:</span><span class="info-value">{escape(str(composition.get('angle', 'N/A')))}</span></div>
                </div>
            </div>
"""

            # Center panel image with overlays
            dialogues = panel.get("dialogue", [])
            sfx_list = panel.get("sfx", [])
            panel_json = json.dumps(panel, indent=2)
            scene_json = json.dumps(scene, indent=2)
            # Get metadata JSON path
            metadata_url = p['url'].replace('.png', '.json')

            html += f"""
            <div class="panel">
"""
            if p["exists"]:
                html += f"""                <img src="{p['url']}" alt="Scene {p['scene_num']} Panel {p['panel_num']}" loading="lazy">
"""
            else:
                html += f"""                <div class="placeholder">Panel not generated yet</div>
"""

            # Add dialogue/SFX overlays (always visible)
            if dialogues or sfx_list:
                html += """                <div class="panel-overlays">
"""
                # SFX at top right
                if sfx_list:
                    html += """                    <div class="sfx-overlay">
"""
                    for sfx in sfx_list:
                        html += f"""                        <span class="sfx-text">{escape(sfx)}</span>
"""
                    html += """                    </div>
"""
                # Dialogue bubbles at bottom
                for dlg in dialogues:
                    dlg_char_id = dlg.get("character_id", "")
                    dlg_char = char_lookup.get(dlg_char_id, {})
                    dlg_name = dlg_char.get("name", dlg_char_id) if dlg_char_id else "Narrator"
                    dlg_text = dlg.get("text", "")
                    dlg_type = dlg.get("type", "speech")
                    bubble_class = dlg_type if dlg_type in ["thought", "narration"] else ""
                    html += f"""                    <div class="dialogue-bubble {bubble_class}">
                        <div class="speaker">{escape(dlg_name)}</div>
                        {escape(dlg_text)}
                    </div>
"""
                html += """                </div>
"""
            html += """            </div>
"""

            # Right debug panel - just an inspect button
            if debug_mode:
                # Escape JSON for data attributes
                panel_json_escaped = escape(panel_json)
                scene_json_escaped = escape(scene_json)
                html += f"""
            <div class="debug-right">
                <button class="inspect-btn" onclick="openJsonModal(this)"
                        data-panel='{panel_json_escaped}'
                        data-scene='{scene_json_escaped}'
                        data-metadata-url="{metadata_url}"
                        data-panel-num="{p['panel_num']}"
                        data-scene-num="{p['scene_num']}">
                    JSON
                </button>
            </div>
"""

            html += """
        </div>
"""

        # Next/prev chapter links
        prev_ch = chapter_num - 1 if chapter_num > 1 else None
        next_ch = chapter_num + 1 if chapter_num < len(chapters) else None

        html += f"""
        <div class="end-card">
            <h2>End of Chapter {chapter_num}</h2>
"""
        if prev_ch:
            html += f"""            <a href="/view/{project_id}/chapter/{prev_ch}">&larr; Previous Chapter</a>
"""
        html += f"""            <a href="/project/{project_id}">Back to Overview</a>
"""
        if next_ch:
            html += f"""            <a href="/view/{project_id}/chapter/{next_ch}">Next Chapter &rarr;</a>
"""
        html += """
        </div>
    </div>

    <!-- JSON Modal for debug inspection -->
    <div id="jsonModal" class="json-modal" onclick="if(event.target === this) closeJsonModal()">
        <div class="json-modal-content">
            <div class="json-modal-header">
                <span class="json-modal-title" id="jsonModalTitle">Panel Data</span>
                <span class="json-modal-close" onclick="closeJsonModal()">&times;</span>
            </div>
            <div class="json-modal-tabs">
                <div class="json-tab active" onclick="showTab('panel')">Panel</div>
                <div class="json-tab" onclick="showTab('scene')">Scene</div>
                <div class="json-tab" onclick="showTab('metadata')">Output Metadata</div>
            </div>
            <div class="json-modal-body">
                <pre class="json-content" id="jsonContent"></pre>
            </div>
        </div>
    </div>

    <script>
    let currentJsonData = { panel: '', scene: '', metadata: null, metadataUrl: '' };

    function syntaxHighlight(json) {
        if (typeof json !== 'string') {
            json = JSON.stringify(json, null, 2);
        }
        json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\\s*:)?|\\b(true|false|null)\\b|-?\\d+(?:\\.\\d*)?(?:[eE][+\\-]?\\d+)?)/g, function (match) {
            let cls = 'number';
            if (/^"/.test(match)) {
                if (/:$/.test(match)) {
                    cls = 'key';
                } else {
                    cls = 'string';
                }
            } else if (/true|false/.test(match)) {
                cls = 'boolean';
            } else if (/null/.test(match)) {
                cls = 'null';
            }
            return '<span class="' + cls + '">' + match + '</span>';
        });
    }

    async function openJsonModal(btn) {
        const panelData = btn.dataset.panel;
        const sceneData = btn.dataset.scene;
        const metadataUrl = btn.dataset.metadataUrl;
        const panelNum = btn.dataset.panelNum;
        const sceneNum = btn.dataset.sceneNum;

        currentJsonData.panel = panelData;
        currentJsonData.scene = sceneData;
        currentJsonData.metadataUrl = metadataUrl;
        currentJsonData.metadata = null;

        document.getElementById('jsonModalTitle').textContent = `Scene ${sceneNum} / Panel ${panelNum}`;
        showTab('panel');
        document.getElementById('jsonModal').classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    async function showTab(tab) {
        document.querySelectorAll('.json-tab').forEach(t => t.classList.remove('active'));
        document.querySelector(`.json-tab:nth-child(${tab === 'panel' ? 1 : tab === 'scene' ? 2 : 3})`).classList.add('active');

        let content = '';
        if (tab === 'panel') {
            content = currentJsonData.panel;
        } else if (tab === 'scene') {
            content = currentJsonData.scene;
        } else if (tab === 'metadata') {
            if (currentJsonData.metadata === null) {
                try {
                    const resp = await fetch(currentJsonData.metadataUrl);
                    if (resp.ok) {
                        currentJsonData.metadata = await resp.text();
                    } else {
                        currentJsonData.metadata = '{"error": "Metadata file not found"}';
                    }
                } catch (e) {
                    currentJsonData.metadata = '{"error": "Failed to load metadata"}';
                }
            }
            content = currentJsonData.metadata;
        }

        try {
            const parsed = JSON.parse(content);
            document.getElementById('jsonContent').innerHTML = syntaxHighlight(JSON.stringify(parsed, null, 2));
        } catch {
            document.getElementById('jsonContent').textContent = content;
        }
    }

    function closeJsonModal() {
        document.getElementById('jsonModal').classList.remove('active');
        document.body.style.overflow = '';
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeJsonModal();
    });
    </script>
</body>
</html>
"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def send_projects_list(self):
        """Send JSON list of projects."""
        projects = []
        if PROJECTS_DIR.exists():
            for project_dir in PROJECTS_DIR.iterdir():
                if project_dir.is_dir():
                    project_json = project_dir / "project.json"
                    if project_json.exists():
                        data = json.loads(project_json.read_text())
                        story = data.get("story", {})
                        projects.append(
                            {
                                "id": project_dir.name,
                                "title": story.get("title", "Untitled"),
                                "chapters": len(data.get("chapters", [])),
                            }
                        )

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(projects).encode())

    def send_project_data(self, project_id: str):
        """Send JSON data for a specific project."""
        project_json = PROJECTS_DIR / project_id / "project.json"
        if project_json.exists():
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(project_json.read_bytes())
        else:
            self.send_error(404, "Project not found")


def run_server(port: int = DEFAULT_PORT, projects_dir: str | None = None):
    """Run the web server."""
    global PROJECTS_DIR

    if projects_dir:
        PROJECTS_DIR = Path(projects_dir)
    else:
        PROJECTS_DIR = Path.cwd() / "projects"

    os.chdir(Path(__file__).parent)

    with socketserver.TCPServer(("", port), WebtoonHandler) as httpd:
        print(f"DreamWright Viewer running at http://localhost:{port}")
        print(f"Projects directory: {PROJECTS_DIR}")
        print("Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


def main():
    parser = argparse.ArgumentParser(description="DreamWright Viewer - Local webtoon viewer")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT, help="Port to run on")
    parser.add_argument("--projects", type=str, default=None, help="Projects directory")
    args = parser.parse_args()

    run_server(port=args.port, projects_dir=args.projects)


if __name__ == "__main__":
    main()
