from __future__ import annotations

import shutil
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image, ImageOps


class CompressionError(Exception):
    pass


@dataclass(frozen=True)
class CompressionSettings:
    pdf_dpi: int
    image_quality: int
    png_colors: int
    max_dimension: int

    @classmethod
    def from_profile(cls, profile: str) -> "CompressionSettings":
        profiles = {
            "small":    cls(pdf_dpi=96,  image_quality=42, png_colors=96,  max_dimension=1400),
            "balanced": cls(pdf_dpi=130, image_quality=60, png_colors=160, max_dimension=2000),
            "quality":  cls(pdf_dpi=180, image_quality=78, png_colors=256, max_dimension=2600),
        }
        return profiles.get(profile, profiles["balanced"])


@dataclass(frozen=True)
class CompressionResult:
    original_size: int
    compressed_size: int
    mimetype: str
    output_path: Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compress_file(input_path: Path, output_path: Path, settings: CompressionSettings) -> CompressionResult:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        return compress_pdf(input_path, output_path, settings)
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return compress_image(input_path, output_path, settings)
    raise CompressionError("Unsupported file type.")


def compress_bytes(
    input_data: bytes,
    suffix: str,
    settings: CompressionSettings
) -> tuple[bytes, str, int, int, str]:
    print("compress_bytes received =", repr(suffix))
    print("Entered compress_pdf_bytes")
    print("=" * 50)
    print("compress_bytes()")
    print("suffix:", repr(suffix))
    print("input size:", len(input_data))
    print("=" * 50)

    suffix = suffix.lower()

    if suffix == ".pdf":
        print("Processing PDF...")
        output_data = compress_pdf_bytes(input_data, settings)
        return (
            output_data,
            "application/pdf",
            len(input_data),
            len(output_data),
            ".pdf",
        )

    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        print("Processing Image...")
        output_data, mimetype, output_suffix = compress_image_bytes(
            input_data,
            suffix,
            settings,
        )
        return (
            output_data,
            mimetype,
            len(input_data),
            len(output_data),
            output_suffix,
        )

    print("UNSUPPORTED SUFFIX:", repr(suffix))
    raise CompressionError(f"Unsupported file type: {suffix}")


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def _is_scanned_pdf(source: fitz.Document, sample_pages: int = 3) -> bool:
    """
    Heuristic: a page is 'scanned' if it has at least one large image and
    very little extractable text. We sample the first few pages only.
    """
    pages_to_check = min(sample_pages, source.page_count)
    scanned_count = 0

    for i in range(pages_to_check):
        page = source[i]
        text = page.get_text().strip()
        images = page.get_images(full=False)

        page_area = page.rect.width * page.rect.height
        large_images = 0
        for img in images:
            rects = page.get_image_rects(img[0])
            for r in rects:
                if r.width * r.height > page_area * 0.20:
                    large_images += 1

        if large_images >= 1 and len(text) < 100:
            scanned_count += 1

    return scanned_count >= max(1, pages_to_check // 2)


def _native_compress_bytes(input_data: bytes) -> bytes:
    """
    Compress using fitz garbage collection + deflate — no re-rasterisation.
    Best for text/vector PDFs.
    """
    with fitz.open(stream=input_data, filetype="pdf") as doc:
        return doc.tobytes(garbage=4, deflate=True, deflate_images=True,
                           deflate_fonts=True, clean=True)


def _raster_compress_bytes(input_data: bytes, settings: CompressionSettings) -> bytes:
    """
    Compress by re-rasterising every page to JPEG.
    Best for scanned documents.
    """
    source = fitz.open(stream=input_data, filetype="pdf")
    target = fitz.open()

    try:
        for page in source:
            pixmap = page.get_pixmap(dpi=settings.pdf_dpi, alpha=False)
            image_bytes = pixmap.tobytes("jpg", jpg_quality=settings.image_quality)
            new_page = target.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(
                fitz.Rect(0, 0, page.rect.width, page.rect.height),
                stream=image_bytes,
            )
        return target.tobytes(garbage=4, deflate=True, clean=True)
    except RuntimeError as exc:
        raise CompressionError("Unable to compress this PDF.") from exc
    finally:
        source.close()
        target.close()


def compress_pdf_bytes(input_data: bytes, settings: CompressionSettings) -> bytes:
    original_size = len(input_data)

    print(f"Original PDF: {original_size:,} bytes")

    try:
        native = _native_compress_bytes(input_data)
        print(f"Native PDF: {len(native):,} bytes")
    except Exception as e:
        print(f"Native compression failed: {e}")
        native = input_data

    try:
        raster = _raster_compress_bytes(input_data, settings)
        print(f"Raster PDF: {len(raster):,} bytes")
    except Exception as e:
        print(f"Raster compression failed: {e}")
        raster = input_data

    best = min([input_data, native, raster], key=len)

    print(f"Selected PDF: {len(best):,} bytes")

    return best


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def compress_image_bytes(input_data: bytes, suffix: str, settings: CompressionSettings) -> tuple[bytes, str, str]:
    try:
        with Image.open(BytesIO(input_data)) as image:
            image = ImageOps.exif_transpose(image)
            resized = _resize_image(image, settings.max_dimension)
            output = BytesIO()

            if suffix == ".png":
                if resized.mode not in ("RGB", "P"):
                    resized = resized.convert("RGBA" if "A" in resized.mode else "RGB")
                converted = resized.convert("P", palette=Image.Palette.ADAPTIVE, colors=settings.png_colors)
                converted.save(output, format="PNG", optimize=True)
                result = output.getvalue()
                return (result, "image/png", ".png") if len(result) < len(input_data) else (input_data, "image/png", ".png")

            if resized.mode not in ("RGB", "L"):
                resized = resized.convert("RGB")
            resized.save(output, format="JPEG", quality=settings.image_quality,
                         optimize=True, progressive=True)
            result = output.getvalue()
            return (result, "image/jpeg", ".jpg") if len(result) < len(input_data) else (input_data, "image/jpeg", ".jpg")
    except OSError as exc:
        raise CompressionError("Unable to compress this image.") from exc


# ---------------------------------------------------------------------------
# File-path variants
# ---------------------------------------------------------------------------

def compress_image(input_path: Path, output_path: Path, settings: CompressionSettings) -> CompressionResult:
    original_size = input_path.stat().st_size

    with Image.open(input_path) as image:
        image = ImageOps.exif_transpose(image)
        resized = _resize_image(image, settings.max_dimension)

        if input_path.suffix.lower() == ".png":
            if resized.mode not in ("RGB", "P"):
                resized = resized.convert("RGBA" if "A" in resized.mode else "RGB")
            converted = resized.convert("P", palette=Image.Palette.ADAPTIVE, colors=settings.png_colors)
            converted.save(output_path, format="PNG", optimize=True)
            mimetype = "image/png"
            final_output_path = output_path
        else:
            if resized.mode not in ("RGB", "L"):
                resized = resized.convert("RGB")
            final_output_path = output_path.with_suffix(".jpg")
            resized.save(final_output_path, format="JPEG", quality=settings.image_quality,
                         optimize=True, progressive=True)
            mimetype = "image/jpeg"

    compressed_size = final_output_path.stat().st_size
    if compressed_size >= original_size:
        shutil.copy2(input_path, final_output_path)
        compressed_size = original_size

    return CompressionResult(
        original_size=original_size,
        compressed_size=compressed_size,
        mimetype=mimetype,
        output_path=final_output_path,
    )


def compress_pdf(input_path: Path, output_path: Path, settings: CompressionSettings) -> CompressionResult:
    original_size = input_path.stat().st_size
    input_data = input_path.read_bytes()
    compressed = compress_pdf_bytes(input_data, settings)
    output_path.write_bytes(compressed)

    return CompressionResult(
        original_size=original_size,
        compressed_size=len(compressed),
        mimetype="application/pdf",
        output_path=output_path,
    )


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

def _resize_image(image: Image.Image, max_dimension: int) -> Image.Image:
    width, height = image.size
    longest_side = max(width, height)
    if longest_side <= max_dimension:
        return image.copy()

    scale = max_dimension / longest_side
    new_size = (max(int(width * scale), 1), max(int(height * scale), 1))
    return image.resize(new_size, Image.Resampling.LANCZOS)