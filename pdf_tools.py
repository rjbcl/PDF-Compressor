from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import fitz
from PIL import Image, ImageOps


class DocumentToolError(Exception):
    pass


@dataclass(frozen=True)
class ToolResult:
    output_path: Path
    mimetype: str
    download_name: str


def merge_pdfs(input_paths: list[Path], output_path: Path) -> ToolResult:
    merged = fitz.open()

    try:
        for path in input_paths:
            with fitz.open(path) as source:
                if source.page_count == 0:
                    raise DocumentToolError(f"{path.name} has no pages to merge.")
                merged.insert_pdf(source)

        if merged.page_count == 0:
            raise DocumentToolError("Choose at least one PDF file to merge.")

        merged.save(output_path, garbage=4, deflate=True)
    except DocumentToolError:
        raise
    except RuntimeError as exc:
        raise DocumentToolError("Unable to merge the selected PDF files.") from exc
    finally:
        merged.close()

    return ToolResult(
        output_path=output_path,
        mimetype="application/pdf",
        download_name=output_path.name,
    )


def merge_pdf_bytes(files: list[tuple[str, bytes]]) -> bytes:
    merged = fitz.open()

    try:
        for filename, data in files:
            with fitz.open(stream=data, filetype="pdf") as source:
                if source.page_count == 0:
                    raise DocumentToolError(f"{filename} has no pages to merge.")
                merged.insert_pdf(source)

        if merged.page_count == 0:
            raise DocumentToolError("Choose at least one PDF file to merge.")

        return merged.tobytes(garbage=4, deflate=True)
    except DocumentToolError:
        raise
    except RuntimeError as exc:
        raise DocumentToolError("Unable to merge the selected PDF files.") from exc
    finally:
        merged.close()


def get_pdf_page_count_bytes(input_data: bytes) -> int:
    try:
        with fitz.open(stream=input_data, filetype="pdf") as source:
            return source.page_count
    except RuntimeError as exc:
        raise DocumentToolError("Unable to read this PDF.") from exc


def split_pdf(input_path: Path, output_path: Path, ranges_text: str, output_mode: str = "zip") -> ToolResult:
    ranges = _parse_page_ranges(ranges_text)
    if not ranges:
        raise DocumentToolError("Enter at least one page range, for example 1-2, 4, 7-9.")

    if output_mode not in {"zip", "merged"}:
        raise DocumentToolError("Choose a valid split output option.")

    try:
        with fitz.open(input_path) as source:
            page_count = source.page_count
            if page_count == 0:
                raise DocumentToolError("This PDF has no pages to split.")

            _validate_ranges(ranges, page_count)

            if output_mode == "merged":
                selected = fitz.open()
                try:
                    for start, end in ranges:
                        selected.insert_pdf(source, from_page=start - 1, to_page=end - 1)
                    selected.save(output_path, garbage=4, deflate=True)
                finally:
                    selected.close()

                return ToolResult(
                    output_path=output_path,
                    mimetype="application/pdf",
                    download_name=output_path.name,
                )

            stem = input_path.stem
            with ZipFile(output_path, "w", ZIP_DEFLATED) as archive:
                for index, (start, end) in enumerate(ranges, start=1):
                    part = fitz.open()
                    try:
                        part.insert_pdf(source, from_page=start - 1, to_page=end - 1)
                        archive.writestr(
                            f"{stem}-part-{index:02d}-pages-{start}-{end}.pdf",
                            part.tobytes(garbage=4, deflate=True),
                        )
                    finally:
                        part.close()
    except DocumentToolError:
        raise
    except RuntimeError as exc:
        raise DocumentToolError("Unable to split this PDF.") from exc

    return ToolResult(
        output_path=output_path,
        mimetype="application/zip",
        download_name=output_path.name,
    )


def split_pdf_bytes(input_data: bytes, stem: str, ranges_text: str, output_mode: str = "zip") -> tuple[bytes, str, str]:
    ranges = _parse_page_ranges(ranges_text)
    if not ranges:
        raise DocumentToolError("Enter at least one page range, for example 1-2, 4, 7-9.")

    if output_mode not in {"zip", "merged"}:
        raise DocumentToolError("Choose a valid split output option.")

    try:
        with fitz.open(stream=input_data, filetype="pdf") as source:
            page_count = source.page_count
            if page_count == 0:
                raise DocumentToolError("This PDF has no pages to split.")

            _validate_ranges(ranges, page_count)

            if output_mode == "merged":
                selected = fitz.open()
                try:
                    for start, end in ranges:
                        selected.insert_pdf(source, from_page=start - 1, to_page=end - 1)
                    return selected.tobytes(garbage=4, deflate=True), "application/pdf", "split-selected-pages.pdf"
                finally:
                    selected.close()

            archive_buffer = BytesIO()
            with ZipFile(archive_buffer, "w", ZIP_DEFLATED) as archive:
                for index, (start, end) in enumerate(ranges, start=1):
                    part = fitz.open()
                    try:
                        part.insert_pdf(source, from_page=start - 1, to_page=end - 1)
                        archive.writestr(
                            f"{stem}-part-{index:02d}-pages-{start}-{end}.pdf",
                            part.tobytes(garbage=4, deflate=True),
                        )
                    finally:
                        part.close()

            return archive_buffer.getvalue(), "application/zip", "split-parts.zip"
    except DocumentToolError:
        raise
    except RuntimeError as exc:
        raise DocumentToolError("Unable to split this PDF.") from exc


def convert_to_pdf(input_path: Path, output_path: Path) -> ToolResult:
    try:
        with Image.open(input_path) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(output_path, format="PDF", resolution=150.0)
    except OSError as exc:
        raise DocumentToolError("Unable to convert this image to PDF.") from exc

    return ToolResult(
        output_path=output_path,
        mimetype="application/pdf",
        download_name=output_path.name,
    )


def convert_image_to_pdf_bytes(input_data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(input_data)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode != "RGB":
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="PDF", resolution=150.0)
            return output.getvalue()
    except OSError as exc:
        raise DocumentToolError("Unable to convert this image to PDF.") from exc


def convert_image_files_to_pdf_bytes(files: list[tuple[str, bytes]]) -> bytes:
    images = []

    try:
        for filename, data in files:
            with Image.open(BytesIO(data)) as image:
                image = ImageOps.exif_transpose(image)
                if image.mode != "RGB":
                    image = image.convert("RGB")
                images.append(image.copy())

        if not images:
            raise DocumentToolError("Choose at least one image to convert.")

        output = BytesIO()
        first_image, *rest = images
        first_image.save(output, format="PDF", resolution=150.0, save_all=True, append_images=rest)
        return output.getvalue()
    except OSError as exc:
        raise DocumentToolError("Unable to convert these images to PDF.") from exc
    finally:
        for image in images:
            image.close()


def convert_pdf_to_jpg_zip(input_path: Path, output_path: Path) -> ToolResult:
    try:
        with fitz.open(input_path) as source, ZipFile(output_path, "w", ZIP_DEFLATED) as archive:
            if source.page_count == 0:
                raise DocumentToolError("This PDF has no pages to convert.")

            for page_number, page in enumerate(source, start=1):
                pixmap = page.get_pixmap(dpi=150, alpha=False)
                archive.writestr(
                    f"{input_path.stem}-page-{page_number:02d}.jpg",
                    pixmap.tobytes("jpg", jpg_quality=82),
                )
    except DocumentToolError:
        raise
    except RuntimeError as exc:
        raise DocumentToolError("Unable to convert this PDF to JPG images.") from exc

    return ToolResult(
        output_path=output_path,
        mimetype="application/zip",
        download_name=output_path.name,
    )


def convert_pdf_to_jpg_zip_bytes(input_data: bytes, stem: str) -> bytes:
    try:
        output = BytesIO()
        with fitz.open(stream=input_data, filetype="pdf") as source, ZipFile(output, "w", ZIP_DEFLATED) as archive:
            if source.page_count == 0:
                raise DocumentToolError("This PDF has no pages to convert.")

            for page_number, page in enumerate(source, start=1):
                pixmap = page.get_pixmap(dpi=150, alpha=False)
                archive.writestr(
                    f"{stem}-page-{page_number:02d}.jpg",
                    pixmap.tobytes("jpg", jpg_quality=82),
                )
        return output.getvalue()
    except DocumentToolError:
        raise
    except RuntimeError as exc:
        raise DocumentToolError("Unable to convert this PDF to JPG images.") from exc


def _parse_page_ranges(ranges_text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []

    for chunk in ranges_text.split(","):
        token = chunk.strip()
        if not token:
            continue

        if "-" in token:
            start_text, end_text = token.split("-", 1)
            if not start_text.strip().isdigit() or not end_text.strip().isdigit():
                raise DocumentToolError("Use page numbers like 1-3, 4, 7-9.")
            start = int(start_text)
            end = int(end_text)
        else:
            if not token.isdigit():
                raise DocumentToolError("Use page numbers like 1-3, 4, 7-9.")
            start = end = int(token)

        if start <= 0 or end <= 0 or end < start:
            raise DocumentToolError("Page ranges must be positive and ordered like 2-5.")

        ranges.append((start, end))

    return ranges


def _validate_ranges(ranges: list[tuple[int, int]], page_count: int) -> None:
    for start, end in ranges:
        if start < 1 or end > page_count:
            label = str(start) if start == end else f"{start}-{end}"
            raise DocumentToolError(
                f"Page range {label} is outside this PDF. It has {page_count} page(s)."
            )
