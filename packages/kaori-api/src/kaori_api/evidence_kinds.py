"""
The kinds of evidence validators check (photo, data, audio, video), which files each kind accepts, and how each is
prepared for a validator.

A validator checks evidence without seeing whose report it is, where or when it was made, or what the reporter
said. So nothing served to a validator may carry place, time or identity: a photo is re-encoded without its EXIF,
a data file loses its location, time and identity fields, and a recording loses its container metadata.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Optional, Tuple

LOGGER = logging.getLogger(__name__)

MB = 1024 * 1024

MIME_TYPES: Dict[str, Tuple[str, ...]] = {
    "photo": ("image/jpeg", "image/png", "image/heic", "image/webp"),
    "data": ("application/json", "text/csv"),
    "audio": ("audio/mpeg", "audio/mp4", "audio/aac", "audio/wav", "audio/x-wav", "audio/ogg", "audio/webm"),
    "video": ("video/mp4", "video/quicktime", "video/webm"),
}
KINDS = tuple(MIME_TYPES)
_KIND_OF = {mime: kind for kind, mimes in MIME_TYPES.items() for mime in mimes}

# Upload limits per kind. A photo keeps the evidence store's own limit (KAORI_MAX_EVIDENCE_BYTES).
MAX_BYTES: Dict[str, Optional[int]] = {"photo": None, "data": 2 * MB, "audio": 20 * MB, "video": 30 * MB}  # Cloud Run caps an HTTP/1 request at 32 MB

# Keys (JSON) and columns (CSV) that could reveal where, when or by whom: removed before a validator sees data.
IDENTIFYING_KEYS = frozenset({
    "lat", "lon", "lng", "latitude", "longitude", "geo", "location", "time", "timestamp", "date",
    "reported_at", "device", "user", "agent", "reporter", "id",
})

# ffmpeg output format and file suffix for each recording type (remux only, no re-encode)
_CONTAINERS = {
    "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/aac": ".aac", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/ogg": ".ogg", "audio/webm": ".webm",
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
}


class EvidenceNotReadable(Exception):
    """Stored evidence could not be prepared for a validator."""


def normalize_mime(mime: Optional[str]) -> str:
    return (mime or "").split(";", 1)[0].strip().lower()


def kind_of(mime: Optional[str]) -> Optional[str]:
    """The evidence kind for a MIME type, or None when validators cannot use it."""
    return _KIND_OF.get(normalize_mime(mime))


def ref_kind(ref: Any) -> Optional[str]:
    """The kind of a stored EvidenceRef. Refs from before MIME types were recorded are photos."""
    mime = getattr(ref, "mime_type", None)
    return "photo" if not mime else kind_of(mime)


def accepted_summary() -> str:
    return "; ".join(f"{kind}: {', '.join(mimes)}" for kind, mimes in MIME_TYPES.items())


# --------------------------------------------------------------------------------------------- photo

def strip_photo(raw: bytes) -> bytes:
    """Re-encode as JPEG without metadata (EXIF GPS and time would reveal the place)."""
    from PIL import Image, ImageOps

    try:
        from pillow_heif import register_heif_opener  # optional: HEIC photos from iPhones

        register_heif_opener()
    except Exception:
        pass
    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1600, 1600))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
    return out.getvalue()


# --------------------------------------------------------------------------------------------- data

def _snake(key: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", key.strip()).lower()


def is_identifying(key: Any) -> bool:
    """A location, time or identity-like key: `lat`, `reported_at`, `deviceId`, `user_id`, `start time` ..."""
    if not isinstance(key, str):
        return False
    snake = _snake(key)
    if snake in IDENTIFYING_KEYS:
        return True
    return any(part in IDENTIFYING_KEYS for part in re.split(r"[^a-z0-9]+", snake) if part)


def _strip_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_json(v) for k, v in value.items() if not is_identifying(k)}
    if isinstance(value, list):
        return [_strip_json(v) for v in value]
    return value


def strip_data(raw: bytes, mime: str) -> bytes:
    """JSON or CSV with location, time and identity-like keys or columns removed."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EvidenceNotReadable("data is not UTF-8 text") from exc
    if normalize_mime(mime) == "application/json":
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise EvidenceNotReadable("data is not valid JSON") from exc
        return json.dumps(_strip_json(parsed), ensure_ascii=False).encode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return b""
    keep = [i for i, name in enumerate(rows[0]) if not is_identifying(name)]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in rows:
        writer.writerow([row[i] for i in keep if i < len(row)])
    return out.getvalue().encode("utf-8")


# --------------------------------------------------------------------------------------------- audio and video

_warned_no_ffmpeg = False


def strip_media(raw: bytes, mime: str) -> bytes:
    """Remux without container metadata (`ffmpeg -map_metadata -1`, no re-encode). Without ffmpeg on PATH the
    recording is served as stored, and a warning is logged once."""
    global _warned_no_ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        if not _warned_no_ffmpeg:
            LOGGER.warning("ffmpeg is not on PATH: audio and video evidence is served with its metadata")
            _warned_no_ffmpeg = True
        return raw
    suffix = _CONTAINERS.get(normalize_mime(mime), ".bin")
    with tempfile.TemporaryDirectory(prefix="kaori-media-") as tmp:
        src, dst = os.path.join(tmp, "in" + suffix), os.path.join(tmp, "out" + suffix)
        with open(src, "wb") as fh:
            fh.write(raw)
        cmd = [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", src, "-map", "0", "-c", "copy",
               "-map_metadata", "-1", "-map_chapters", "-1", dst]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            with open(dst, "rb") as fh:
                return fh.read()
        except (subprocess.SubprocessError, OSError) as exc:
            raise EvidenceNotReadable("recording could not be remuxed") from exc


def prepare(raw: bytes, kind: str, mime: Optional[str]) -> Tuple[bytes, str]:
    """(bytes, content type) as a validator receives them."""
    if kind == "photo":
        try:
            return strip_photo(raw), "image/jpeg"
        except Exception as exc:
            raise EvidenceNotReadable("photo is not a readable image") from exc
    if kind == "data":
        return strip_data(raw, mime or ""), normalize_mime(mime)
    if kind in ("audio", "video"):
        return strip_media(raw, mime or ""), normalize_mime(mime)
    raise EvidenceNotReadable("unsupported evidence kind")
