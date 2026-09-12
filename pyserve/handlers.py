"""Built-in request handlers - static files, directory listing."""
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pyserve.parser import Request
from pyserve.response import Response, guess_content_type, http_date


class StaticFileHandler:
    """Serves files from a base directory. Safe against path traversal."""

    def __init__(self, root: str, index_files: Optional[list] = None):
        self.root = Path(root).resolve()
        self.index_files = index_files or ["index.html", "index.htm"]
        if not self.root.exists():
            raise ValueError(f"Static root does not exist: {self.root}")
        if not self.root.is_dir():
            raise ValueError(f"Static root is not a directory: {self.root}")

    def _safe_path(self, url_path: str) -> Optional[Path]:
        """Resolve url_path under root, returning None if it escapes."""
        from urllib.parse import unquote
        decoded = unquote(url_path.lstrip("/"))

        if ".." in decoded.split("/"):
            return None
        if "\x00" in decoded:
            return None

        candidate = (self.root / decoded).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None

        return candidate

    def handle(self, request: Request, url_path: Optional[str] = None) -> Response:
        path = url_path if url_path is not None else request.path

        if request.method not in ("GET", "HEAD"):
            resp = Response.text("Method Not Allowed", status=405)
            resp.set_header("Allow", "GET, HEAD")
            return resp

        target = self._safe_path(path)
        if target is None:
            return Response.text("Forbidden", status=403)

        if target.is_dir():
            for index_name in self.index_files:
                index_file = target / index_name
                if index_file.is_file():
                    target = index_file
                    break
            else:
                return self._directory_listing(target, path)

        if not target.is_file():
            return Response.not_found()

        try:
            stat = target.stat()
            body = target.read_bytes()
        except OSError as e:
            return Response.server_error(f"Could not read file: {e}")

        resp = Response(
            status=200,
            body=body,
            headers={
                "Content-Type": guess_content_type(str(target)),
                "Last-Modified": http_date(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
                "ETag": f'"{int(stat.st_mtime)}-{stat.st_size}"',
                "Cache-Control": "public, max-age=3600",
            },
        )
        return resp

    def _directory_listing(self, directory: Path, url_path: str) -> Response:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as e:
            return Response.server_error(f"Could not read directory: {e}")

        rows = []
        if directory != self.root:
            rows.append('<li><a href="../">../</a></li>')
        for entry in entries:
            name = entry.name
            suffix = "/" if entry.is_dir() else ""
            link = html.escape(name + suffix)
            rows.append(f'<li><a href="{link}">{link}</a></li>')

        body = f"""<!DOCTYPE html>
<html><head><title>Index of {html.escape(url_path)}</title></head>
<body><h1>Index of {html.escape(url_path)}</h1>
<ul>{''.join(rows)}</ul>
<hr><p><em>PyServe</em></p></body></html>"""
        return Response.html(body)

    def __repr__(self) -> str:
        return f"<StaticFileHandler root={self.root}>"