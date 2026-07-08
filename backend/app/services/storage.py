"""Persistent file storage for uploaded documents.

Files are stored on a mounted Render disk at ``STORAGE_DIR``. Layout is:

    {storage_dir}/{tenant_id}/{document_id}{suffix}

Suffix is the lowercased original extension (``.pdf``, ``.docx``…). We
persist raw bytes at ingest so the frontend can later stream the original
back via ``GET /api/documents/{id}/file`` — the "click a citation to open
the PDF" flow.

Only newly-uploaded documents get a stored file; docs ingested before this
was wired up have ``source_uri=NULL`` and the frontend disables the "open"
control for them.
"""
from pathlib import Path
from uuid import UUID

from app.config import settings

# Extensions we're willing to serve back to the browser. If the ingest ever
# accepts a new format, add it here so we don't accidentally serve
# something the browser will refuse to render inline.
_INLINE_MIME = {
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
}


def storage_root() -> Path:
    """Root directory for stored files. Created on first use."""
    p = Path(settings.storage_dir).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_original(
    *, tenant_id: UUID, document_id: UUID, suffix: str, contents: bytes
) -> str:
    """Persist raw bytes under storage_dir. Returns a path-style source_uri
    that ``resolve_stored_file`` accepts. Uses ``file://`` prefix so the value
    is unambiguously a local path (vs a future S3 URI)."""
    suffix = (suffix or "").lower()
    dest_dir = storage_root() / str(tenant_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{document_id}{suffix}"
    dest.write_bytes(contents)
    return f"file://{dest}"


def resolve_stored_file(source_uri: str | None) -> Path | None:
    """Return an existing Path for a source_uri written by ``save_original``,
    or None if the URI isn't a local file or the file is gone. Enforces that
    the resolved path stays under storage_root — defensive against path
    escapes if source_uri ever gets tampered with."""
    if not source_uri or not source_uri.startswith("file://"):
        return None
    path = Path(source_uri[len("file://") :]).resolve()
    root = storage_root()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


def guess_content_type(path: Path) -> str:
    return _INLINE_MIME.get(path.suffix.lower(), "application/octet-stream")
