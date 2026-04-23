from __future__ import annotations

from dataclasses import dataclass
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
            "small": cls(pdf_dpi=110, image_quality=50, png_colors=96, max_dimension=1600),
            "balanced": cls(pdf_dpi=150, image_quality=68, png_colors=160, max_dimension=2200),
            "quality": cls(pdf_dpi=200, image_quality=82, png_colors=256, max_dimension=2800),
        }
        return profiles.get(profile, profiles["balanced"])


@dataclass(frozen=True)
class CompressionResult:
    original_size: int
    compressed_size: int
    mimetype: str
    output_path: Path


def compress_file(input_path: Path, output_path: Path, settings: CompressionSettings) -> CompressionResult:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        return compress_pdf(input_path, output_path, settings)
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return compress_image(input_path, output_path, settings)
    raise CompressionError("Unsupported file type.")


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
            resized.save(
                final_output_path,
                format="JPEG",
                quality=settings.image_quality,
                optimize=True,
                progressive=True,
            )
            mimetype = "image/jpeg"

    return CompressionResult(
        original_size=original_size,
        compressed_size=final_output_path.stat().st_size,
        mimetype=mimetype,
        output_path=final_output_path,
    )


def compress_pdf(input_path: Path, output_path: Path, settings: CompressionSettings) -> CompressionResult:
    original_size = input_path.stat().st_size
    source = fitz.open(input_path)
    target = fitz.open()

    try:
        for page in source:
            pixmap = page.get_pixmap(dpi=settings.pdf_dpi, alpha=False)
            image_bytes = pixmap.tobytes("jpg", jpg_quality=settings.image_quality)
            rect = fitz.Rect(0, 0, page.rect.width, page.rect.height)
            new_page = target.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(rect, stream=image_bytes)

        target.save(output_path, garbage=4, deflate=True, clean=True)
    except RuntimeError as exc:
        raise CompressionError("Unable to compress this PDF.") from exc
    finally:
        source.close()
        target.close()

    return CompressionResult(
        original_size=original_size,
        compressed_size=output_path.stat().st_size,
        mimetype="application/pdf",
        output_path=output_path,
    )


def _resize_image(image: Image.Image, max_dimension: int) -> Image.Image:
    width, height = image.size
    longest_side = max(width, height)
    if longest_side <= max_dimension:
        return image.copy()

    scale = max_dimension / longest_side
    new_size = (max(int(width * scale), 1), max(int(height * scale), 1))
    return image.resize(new_size, Image.Resampling.LANCZOS)
