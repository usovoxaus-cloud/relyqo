"""Content-addressed public assets; account documents always remain uncached."""

from functools import lru_cache
from hashlib import sha256
from html import escape, unescape
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PUBLIC_SUFFIXES = {".js", ".css", ".json", ".svg", ".ico", ".woff2"}
_TAG = re.compile(r"<(?:script|link)\b[^>]*>", re.IGNORECASE)
_URL = re.compile(r"(\b(?:src|href)\s*=\s*)([\"'])(/static/[^\"']+)\2", re.IGNORECASE)


@lru_cache(maxsize=512)
def _digest(path: Path, mtime_ns: int, ctime_ns: int, size: int) -> str:
    # Stat metadata invalidates the digest in development without hashing every request.
    return sha256(path.read_bytes()).hexdigest()


class StaticAssets:
    def __init__(self, directory: Path):
        root = directory.resolve()
        # Only bundled public files can receive immutable caching; never use a URL
        # as a filesystem path. HTML and the service worker are deliberately excluded.
        self.files = {
            "/static/" + path.name: path
            for path in root.iterdir()
            if path.is_file() and not path.is_symlink()
            and path.suffix in PUBLIC_SUFFIXES and path.name != "sw.js"
        }

    def digest(self, url_path: str) -> str | None:
        path = self.files.get(url_path)
        if path is None:
            return None
        try:
            stat = path.stat()
            return _digest(path, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        except OSError:
            return None

    def url(self, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme or parts.netloc:
            return value
        digest = self.digest(parts.path)
        if digest is None:
            return value
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "v"]
        query.append(("v", digest))
        return urlunsplit(("", "", parts.path, urlencode(query), parts.fragment))

    def html(self, content: str) -> str:
        def replace_url(match):
            return match[1] + match[2] + escape(self.url(unescape(match[3])), quote=True) + match[2]

        content = _TAG.sub(lambda tag: _URL.sub(replace_url, tag[0]), content)
        # The dictionary is fetched from JavaScript, rather than a script/link tag.
        # A metadata URL versions it independently without downloading it for Russian.
        dictionary = self.url("/static/i18n-uz.json")
        if "?v=" in dictionary:
            meta = '<meta name="relyqo-dictionary" content="' + escape(dictionary, quote=True) + '">'
            content = content.replace("<head>", "<head>" + meta, 1)
        return content

    def cache_control(self, path: str, versions: list[str]) -> str:
        digest = self.digest(path)
        if digest is not None and versions == [digest]:
            return "public, max-age=31536000, immutable"
        if any(re.fullmatch(r"[a-f0-9]{64}", value) for value in versions):
            # A tab from a previous deployment must not store new bytes under an old hash.
            return "no-store"
        return "public, max-age=300, must-revalidate"


assets = StaticAssets(Path(__file__).parent / "static")
