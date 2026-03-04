# AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/coach/tools.py | Copilot
"""Coach Tools — URL fetching, file processing, and slash commands.
Provides multimodal input processing for the Coach engine:
    URLFetcher      — Fetches and extracts readable text from URLs
    FileProcessor   — Extracts text content from uploaded files
    SlashCommands   — Parses and executes /commands
"""
from __future__ import annotations
import base64
import json
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
# ========================================================================
# URL Fetcher — extract readable text from web pages
# ========================================================================
class _TextExtractor(HTMLParser):
    """Simple HTML → text extractor. Skips script/style/nav elements."""
    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "svg"}
    def __init__(self):
        super().__init__()
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self.title = ""
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr"):
            self.text_parts.append("\n")
    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag == "title":
            self._in_title = False
    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip_depth == 0:
            self.text_parts.append(data)
class URLFetcher:
    """Fetches a URL and extracts readable text content."""
    MAX_SIZE = 512_000  # 512KB max download
    TIMEOUT = 15
    def fetch(self, url: str) -> dict:
        """Fetch URL and return extracted text.
        Returns: {"success": bool, "title": str, "text": str, "url": str, "error": str|None}
        """
        if not url or not url.startswith(("http://", "https://")):
            return {"success": False, "title": "", "text": "",
                    "url": url, "error": "Invalid URL — must start with http:// or https://"}
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Hoopla-Coach/1.0 (URL preview)",
                "Accept": "text/html,application/xhtml+xml,text/plain,application/json",
            })
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                content_type = resp.headers.get("Content-Type", "")
                data = resp.read(self.MAX_SIZE)
            text = data.decode("utf-8", errors="replace")
            if "application/json" in content_type:
                # JSON: pretty-print
                try:
                    parsed = json.loads(text)
                    return {"success": True, "title": f"JSON from {url}",
                            "text": json.dumps(parsed, indent=2)[:10000],
                            "url": url, "error": None}
                except json.JSONDecodeError:
                    pass
            if "text/plain" in content_type:
                return {"success": True, "title": url,
                        "text": text[:10000], "url": url, "error": None}
            # HTML: extract readable text
            extractor = _TextExtractor()
            extractor.feed(text)
            clean = re.sub(r"\n{3,}", "\n\n", "".join(extractor.text_parts)).strip()
            title = extractor.title.strip() or url
            return {"success": True, "title": title,
                    "text": clean[:10000], "url": url, "error": None}
        except urllib.error.HTTPError as e:
            return {"success": False, "title": "", "text": "",
                    "url": url, "error": f"HTTP {e.code}: {e.reason}"}
        except urllib.error.URLError as e:
            return {"success": False, "title": "", "text": "",
                    "url": url, "error": f"Network error: {e.reason}"}
        except Exception as e:
            return {"success": False, "title": "", "text": "",
                    "url": url, "error": str(e)}
# ========================================================================
# File Processor — extract text from uploaded files
# ========================================================================
@dataclass
class ProcessedFile:
    """Result of processing an uploaded file."""
    filename: str
    content_type: str
    text: str = ""
    is_image: bool = False
    image_base64: str = ""
    image_media_type: str = ""
    error: str | None = None
class FileProcessor:
    """Extracts readable text content from uploaded files."""
    TEXT_EXTENSIONS = {
        ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml",
        ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
        ".py", ".js", ".ts", ".java", ".kt", ".swift", ".go", ".rs",
        ".html", ".htm", ".css", ".scss", ".less",
        ".sh", ".bash", ".zsh", ".fish",
        ".sql", ".graphql", ".gql",
        ".env", ".gitignore", ".dockerfile",
        ".gradle", ".properties",
    }
    IMAGE_TYPES = {
        "image/png": "image/png",
        "image/jpeg": "image/jpeg",
        "image/gif": "image/gif",
        "image/webp": "image/webp",
        "image/svg+xml": "image/svg+xml",
    }
    MAX_TEXT_SIZE = 100_000  # 100KB text limit
    MAX_IMAGE_SIZE = 5_000_000  # 5MB image limit
    def process(self, filename: str, data: bytes,
                content_type: str = "") -> ProcessedFile:
        """Process an uploaded file and extract content."""
        ext = Path(filename).suffix.lower()
        # Image files → return as base64 for vision
        if content_type in self.IMAGE_TYPES or ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            if len(data) > self.MAX_IMAGE_SIZE:
                return ProcessedFile(
                    filename=filename, content_type=content_type,
                    error=f"Image too large ({len(data) // 1024}KB, max {self.MAX_IMAGE_SIZE // 1024}KB)")
            media_type = self.IMAGE_TYPES.get(
                content_type,
                {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "gif": "image/gif", "webp": "image/webp"}.get(ext.lstrip("."), "image/png")
            )
            return ProcessedFile(
                filename=filename, content_type=content_type,
                is_image=True,
                image_base64=base64.b64encode(data).decode("ascii"),
                image_media_type=media_type,
            )
        # Text-based files
        if ext in self.TEXT_EXTENSIONS or content_type.startswith("text/"):
            try:
                text = data.decode("utf-8", errors="replace")
                if len(text) > self.MAX_TEXT_SIZE:
                    text = text[:self.MAX_TEXT_SIZE] + f"\n\n[Truncated at {self.MAX_TEXT_SIZE // 1000}KB]"
                return ProcessedFile(
                    filename=filename, content_type=content_type,
                    text=text,
                )
            except Exception as e:
                return ProcessedFile(
                    filename=filename, content_type=content_type,
                    error=f"Failed to read text: {e}")
        # PDF: basic text extraction (no external deps)
        if ext == ".pdf" or content_type == "application/pdf":
            text = self._extract_pdf_text(data)
            if text:
                return ProcessedFile(filename=filename, content_type=content_type, text=text)
            return ProcessedFile(
                filename=filename, content_type=content_type,
                error="PDF text extraction requires additional setup. Try pasting the text content instead.")
        return ProcessedFile(
            filename=filename, content_type=content_type,
            error=f"Unsupported file type: {ext or content_type}. Try .txt, .md, .json, .csv, or image files.")
    def _extract_pdf_text(self, data: bytes) -> str:
        """Best-effort PDF text extraction without external dependencies."""
        # Try extracting raw text between stream markers (very basic)
        text_parts = []
        try:
            content = data.decode("latin-1")
            # Find text between BT...ET markers
            for match in re.finditer(r"\(([^)]+)\)", content):
                fragment = match.group(1)
                if len(fragment) > 2 and fragment.isprintable():
                    text_parts.append(fragment)
        except Exception:
            pass
        if text_parts:
            return " ".join(text_parts)[:self.MAX_TEXT_SIZE]
        return ""
# ========================================================================
# Slash Commands — user-invoked tools
# ========================================================================
@dataclass
class CommandResult:
    """Result from executing a slash command."""
    command: str
    success: bool
    output: str
    artifact: dict | None = None  # {type, title, content} for generated artifacts
# Registry of available commands
COMMANDS: dict[str, dict] = {
    "/help": {
        "description": "Show available commands",
        "usage": "/help",
    },
    "/status": {
        "description": "Show business case progress and session info",
        "usage": "/status",
    },
    "/generate": {
        "description": "Generate an artifact (business-case, epic, story, stories-draft)",
        "usage": "/generate <type>  — e.g., /generate business-case",
    },
    "/export": {
        "description": "Export the current conversation as Markdown",
        "usage": "/export [filename]",
    },
    "/fetch": {
        "description": "Fetch and read content from a URL",
        "usage": "/fetch <url>",
    },
    "/reset": {
        "description": "Start a new conversation (current session will be saved)",
        "usage": "/reset",
    },
}
class SlashCommandHandler:
    """Parses and executes /commands in user messages."""
    def __init__(self):
        self.url_fetcher = URLFetcher()
        self._handlers: dict[str, Callable] = {
            "/help": self._cmd_help,
            "/status": self._cmd_status,
            "/generate": self._cmd_generate,
            "/export": self._cmd_export,
            "/fetch": self._cmd_fetch,
            "/reset": self._cmd_reset,
        }
    def is_command(self, text: str) -> bool:
        """Check if a message starts with a slash command."""
        return text.strip().startswith("/") and text.strip().split()[0] in COMMANDS
    def parse(self, text: str) -> tuple[str, str]:
        """Parse a command string into (command, args)."""
        parts = text.strip().split(None, 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        return command, args
    def execute(self, text: str, engine_status: dict | None = None,
                messages: list | None = None) -> CommandResult:
        """Execute a slash command."""
        command, args = self.parse(text)
        handler = self._handlers.get(command)
        if not handler:
            return CommandResult(
                command=command, success=False,
                output=f"Unknown command: `{command}`. Type `/help` for available commands.")
        return handler(args, engine_status=engine_status, messages=messages)
    def get_completions(self, partial: str) -> list[dict]:
        """Return command completions for autocomplete."""
        partial = partial.lower()
        return [
            {"command": cmd, **info}
            for cmd, info in COMMANDS.items()
            if cmd.startswith(partial)
        ]
    # -- Command Implementations --
    def _cmd_help(self, args: str, **_) -> CommandResult:
        lines = ["**Available Commands:**\n"]
        for cmd, info in COMMANDS.items():
            lines.append(f"- `{info['usage']}` — {info['description']}")
        lines.append("\nYou can also paste URLs directly in your message, and Priya will read them.")
        lines.append("Drag & drop or paste images to have Priya analyze them.")
        return CommandResult(command="/help", success=True, output="\n".join(lines))
    def _cmd_status(self, args: str, engine_status: dict | None = None, **_) -> CommandResult:
        if not engine_status:
            return CommandResult(command="/status", success=True,
                                output="No active session. Start a conversation to track progress.")
        s = engine_status
        progress = s.get("progress", {})
        lines = [
            f"**Session Status**",
            f"- Turns: {s.get('turns', 0)}",
            f"- Progress: {progress.get('percent', 0):.0f}%",
            f"- Covered: {', '.join(progress.get('covered', [])) or 'none yet'}",
            f"- Partial: {', '.join(progress.get('partial', [])) or 'none'}",
            f"- Missing: {', '.join(progress.get('missing', [])) or 'none'}",
            f"- Backend: {s.get('backend', 'unknown')}",
        ]
        signals = s.get("signals", {})
        if signals.get("weak"):
            lines.append(f"- ⚠️ Weak signals detected: {len(signals['weak'])}")
        if signals.get("strong"):
            lines.append(f"- ✅ Strong signals: {len(signals['strong'])}")
        return CommandResult(command="/status", success=True, output="\n".join(lines))
    def _cmd_generate(self, args: str, messages: list | None = None, **_) -> CommandResult:
        artifact_type = args.strip().lower() if args else ""
        valid_types = ["business-case", "epic", "epics", "story", "stories-draft"]
        if not artifact_type or artifact_type not in valid_types:
            return CommandResult(
                command="/generate", success=False,
                output=f"Usage: `/generate <type>` where type is one of: {', '.join(valid_types)}\n\n"
                       f"Example: `/generate business-case`")
        # Signal to the engine that the next response should generate an artifact
        return CommandResult(
            command="/generate", success=True,
            output=f"Generating **{artifact_type}** from our conversation so far. "
                   f"I'll produce a structured draft based on what we've discussed.",
            artifact={"type": artifact_type, "action": "generate"})
    def _cmd_export(self, args: str, messages: list | None = None, **_) -> CommandResult:
        # Export is handled client-side; this just confirms
        return CommandResult(
            command="/export", success=True,
            output="Use the **Export** button in the header to download this conversation as Markdown.")
    def _cmd_fetch(self, args: str, **_) -> CommandResult:
        url = args.strip()
        if not url:
            return CommandResult(command="/fetch", success=False,
                                output="Usage: `/fetch <url>` — e.g., `/fetch https://example.com`")
        result = self.url_fetcher.fetch(url)
        if result["success"]:
            title = result["title"]
            text = result["text"]
            # Truncate for display
            preview = text[:2000] + ("…" if len(text) > 2000 else "")
            return CommandResult(
                command="/fetch", success=True,
                output=f"📄 **{title}**\n\n{preview}\n\n---\n*Fetched from {url}*")
        return CommandResult(command="/fetch", success=False,
                            output=f"Failed to fetch URL: {result['error']}")
    def _cmd_reset(self, args: str, **_) -> CommandResult:
        return CommandResult(
            command="/reset", success=True,
            output="Session reset. Starting a fresh conversation.",
            artifact={"type": "reset", "action": "reset"})
# ========================================================================
# URL Detection — find URLs in natural message text
# ========================================================================
_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"')\]]+",
    re.IGNORECASE,
)
def extract_urls(text: str) -> list[str]:
    """Extract HTTP(S) URLs from free-form text."""
    return _URL_PATTERN.findall(text)
