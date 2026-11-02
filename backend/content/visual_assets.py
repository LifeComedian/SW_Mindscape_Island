"""Strict, dependency-free validation for pack-owned raster images."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re
import struct
import zlib


ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
IMAGE_EXTENSION_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_IMAGE_FILE_BYTES = 4_000_000
MAX_IMAGE_WIDTH = 4096
MAX_IMAGE_HEIGHT = 4096
MAX_IMAGE_PIXELS = 16_000_000
MAX_VISUAL_ASSETS = 64
MAX_TOTAL_IMAGE_BYTES = 20_000_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VisualAssetValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedImage:
    mime_type: str
    width: int
    height: int
    sha256: str
    size_bytes: int


def validate_asset_file_name(file_name: str, mime_type: str) -> None:
    """Allow only normalized relative files below the pack's ``assets`` folder."""

    if not isinstance(file_name, str) or not file_name:
        raise VisualAssetValidationError("file_name must be a non-empty string")
    if "\\" in file_name or "\x00" in file_name:
        raise VisualAssetValidationError("file_name must use a normalized relative path")
    path = PurePosixPath(file_name)
    if path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "assets":
        raise VisualAssetValidationError("file_name must be assets/<filename>")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise VisualAssetValidationError("file_name cannot contain traversal segments")
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise VisualAssetValidationError("mime_type must be PNG, JPEG, or WebP")
    suffix = path.suffix.lower()
    expected = IMAGE_EXTENSION_BY_MIME[mime_type]
    if mime_type == "image/jpeg":
        if suffix not in {".jpg", ".jpeg"}:
            raise VisualAssetValidationError("JPEG assets must use .jpg or .jpeg")
    elif suffix != expected:
        raise VisualAssetValidationError(f"{mime_type} assets must use {expected}")
    stem = path.stem
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", stem):
        raise VisualAssetValidationError("asset filename contains unsupported characters")


def validate_image_bytes(
    data: bytes,
    *,
    declared_mime_type: str,
    declared_width: int | None = None,
    declared_height: int | None = None,
    declared_sha256: str | None = None,
) -> ValidatedImage:
    if not data:
        raise VisualAssetValidationError("image file is empty")
    if len(data) > MAX_IMAGE_FILE_BYTES:
        raise VisualAssetValidationError(
            f"image file exceeds {MAX_IMAGE_FILE_BYTES} bytes"
        )
    detected_mime, width, height = _inspect_image(data)
    if detected_mime != declared_mime_type:
        raise VisualAssetValidationError(
            f"file signature is {detected_mime}, not {declared_mime_type}"
        )
    if width < 1 or height < 1:
        raise VisualAssetValidationError("image dimensions must be positive")
    if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
        raise VisualAssetValidationError(
            f"image dimensions exceed {MAX_IMAGE_WIDTH}x{MAX_IMAGE_HEIGHT}"
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise VisualAssetValidationError(
            f"image exceeds {MAX_IMAGE_PIXELS} decoded pixels"
        )
    if declared_width is not None and width != declared_width:
        raise VisualAssetValidationError("image width does not match visuals.json")
    if declared_height is not None and height != declared_height:
        raise VisualAssetValidationError("image height does not match visuals.json")
    digest = hashlib.sha256(data).hexdigest()
    if declared_sha256 is not None:
        if not SHA256_RE.fullmatch(declared_sha256):
            raise VisualAssetValidationError("sha256 must be 64 lowercase hex characters")
        if digest != declared_sha256:
            raise VisualAssetValidationError("image sha256 does not match visuals.json")
    return ValidatedImage(
        mime_type=detected_mime,
        width=width,
        height=height,
        sha256=digest,
        size_bytes=len(data),
    )


def _inspect_image(data: bytes) -> tuple[str, int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = _inspect_png(data)
        return "image/png", width, height
    if data.startswith(b"\xff\xd8"):
        width, height = _inspect_jpeg(data)
        return "image/jpeg", width, height
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        width, height = _inspect_webp(data)
        return "image/webp", width, height
    raise VisualAssetValidationError("file is not a supported PNG, JPEG, or WebP image")


def _inspect_png(data: bytes) -> tuple[int, int]:
    if len(data) < 45:
        raise VisualAssetValidationError("PNG is truncated")
    offset = 8
    width = height = None
    saw_iend = False
    saw_idat = False
    idat_parts: list[bytes] = []
    bit_depth = color_type = None
    chunk_index = 0
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise VisualAssetValidationError("PNG chunk is truncated")
        chunk_data = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            raise VisualAssetValidationError("PNG chunk checksum is invalid")
        if chunk_index == 0:
            if chunk_type != b"IHDR" or length != 13:
                raise VisualAssetValidationError("PNG must start with a valid IHDR chunk")
            width, height = struct.unpack(">II", chunk_data[:8])
            bit_depth, color_type, compression, filtering, interlace = chunk_data[8:13]
            allowed_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if color_type not in allowed_depths or bit_depth not in allowed_depths[color_type]:
                raise VisualAssetValidationError("PNG color type or bit depth is unsupported")
            if compression != 0 or filtering != 0 or interlace != 0:
                raise VisualAssetValidationError("PNG compression, filter, or interlace mode is unsupported")
        if chunk_type == b"IDAT":
            saw_idat = True
            idat_parts.append(chunk_data)
        if chunk_type == b"IEND":
            if length != 0 or end != len(data):
                raise VisualAssetValidationError("PNG IEND chunk is malformed")
            saw_iend = True
            break
        offset = end
        chunk_index += 1
    if not saw_iend or not saw_idat or width is None or height is None:
        raise VisualAssetValidationError("PNG is missing required chunks")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = (width * channels * bit_depth + 7) // 8
    expected_size = (row_bytes + 1) * height
    if expected_size > 80_000_000:
        raise VisualAssetValidationError("PNG decoded byte size is too large")
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(b"".join(idat_parts), expected_size + 1)
        remaining = max(1, expected_size + 1 - len(decoded))
        decoded += decoder.flush(remaining)
    except zlib.error as exc:
        raise VisualAssetValidationError("PNG image data is malformed") from exc
    if (
        len(decoded) != expected_size
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise VisualAssetValidationError("PNG decoded data length is invalid")
    for row in range(height):
        if decoded[row * (row_bytes + 1)] > 4:
            raise VisualAssetValidationError("PNG row filter is invalid")
    return width, height


_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def _inspect_jpeg(data: bytes) -> tuple[int, int]:
    if len(data) < 12 or not data.endswith(b"\xff\xd9"):
        raise VisualAssetValidationError("JPEG is truncated or missing EOI")
    offset = 2
    dimensions: tuple[int, int] | None = None
    while offset < len(data) - 2:
        if data[offset] != 0xFF:
            raise VisualAssetValidationError("JPEG marker stream is malformed")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker == 0xD9:
            break
        if marker in {0x01, *range(0xD0, 0xD8)}:
            continue
        if offset + 2 > len(data):
            raise VisualAssetValidationError("JPEG segment is truncated")
        segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(data):
            raise VisualAssetValidationError("JPEG segment length is invalid")
        if marker in _JPEG_SOF_MARKERS:
            if segment_length < 7:
                raise VisualAssetValidationError("JPEG SOF segment is malformed")
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            dimensions = (width, height)
        if marker == 0xDA:
            # Entropy-coded data is byte-stuffed and may contain restart markers.
            if b"\xff\xd9" not in data[offset + segment_length :]:
                raise VisualAssetValidationError("JPEG scan data is missing EOI")
            break
        offset += segment_length
    if dimensions is None:
        raise VisualAssetValidationError("JPEG has no supported start-of-frame segment")
    return dimensions


def _inspect_webp(data: bytes) -> tuple[int, int]:
    if len(data) < 30:
        raise VisualAssetValidationError("WebP is truncated")
    declared_size = struct.unpack("<I", data[4:8])[0] + 8
    if declared_size != len(data):
        raise VisualAssetValidationError("WebP RIFF size is invalid")
    offset = 12
    dimensions: tuple[int, int] | None = None
    while offset + 8 <= len(data):
        kind = data[offset : offset + 4]
        length = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        start = offset + 8
        end = start + length
        if end > len(data):
            raise VisualAssetValidationError("WebP chunk is truncated")
        payload = data[start:end]
        if kind == b"VP8X":
            if length < 10:
                raise VisualAssetValidationError("WebP VP8X chunk is malformed")
            width = 1 + int.from_bytes(payload[4:7], "little")
            height = 1 + int.from_bytes(payload[7:10], "little")
            dimensions = (width, height)
        elif kind == b"VP8L":
            if length < 5 or payload[0] != 0x2F:
                raise VisualAssetValidationError("WebP VP8L chunk is malformed")
            bits = int.from_bytes(payload[1:5], "little")
            dimensions = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        elif kind == b"VP8 ":
            if length < 10 or payload[3:6] != b"\x9d\x01\x2a":
                raise VisualAssetValidationError("WebP VP8 frame header is malformed")
            width, height = struct.unpack("<HH", payload[6:10])
            dimensions = (width & 0x3FFF, height & 0x3FFF)
        offset = end + (length & 1)
    if offset != len(data) or dimensions is None:
        raise VisualAssetValidationError("WebP has no valid image dimensions")
    return dimensions
