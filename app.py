from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename

from compressor import CompressionError, CompressionSettings, compress_bytes, compress_file
from pdf_tools import (
    DocumentToolError,
    ToolResult,
    convert_image_files_to_pdf_bytes,
    convert_pdf_to_jpg_zip,
    convert_pdf_to_jpg_zip_bytes,
    convert_to_pdf,
    get_pdf_page_count_bytes,
    merge_pdf_bytes,
    merge_pdfs,
    split_pdf,
    split_pdf_bytes,
)


class DownloadResult(Protocol):
    output_path: Path
    mimetype: str
    download_name: str


BASE_DIR = Path(__file__).resolve().parent
RUNTIME_TEMP_DIR = BASE_DIR / ".tmp"

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
PDF_ONLY_EXTENSIONS = {".pdf"}
IMAGE_ONLY_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

RUNTIME_TEMP_DIR.mkdir(exist_ok=True)


def is_allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def has_allowed_extension(filename: str, allowed_extensions: set[str]) -> bool:
    return Path(filename).suffix.lower() in allowed_extensions


def render_tool_page(*, error: str | None = None, active_tool: str = "", status: int = 200):
    return render_template("index.html", error=error, active_tool=active_tool), status


def render_tool_error(message: str, *, active_tool: str, status: int = 400):
    if request.headers.get("X-Requested-With") == "fetch":
        return message, status, {"Content-Type": "text/plain; charset=utf-8"}
    return render_tool_page(error=message, active_tool=active_tool, status=status)


def build_download_response(temp_dir: TemporaryDirectory, result: DownloadResult):
    response = send_file(
        result.output_path,
        as_attachment=True,
        download_name=result.download_name,
        mimetype=result.mimetype,
        etag=False,
        last_modified=None,
        max_age=0,
    )
    response.call_on_close(temp_dir.cleanup)
    return response


def build_memory_download_response(data: bytes, mimetype: str, download_name: str):
    return send_file(
        BytesIO(data),
        as_attachment=True,
        download_name=download_name,
        mimetype=mimetype,
        etag=False,
        last_modified=None,
        max_age=0,
    )


def cleanup_temp_dir(temp_dir: TemporaryDirectory) -> None:
    try:
        temp_dir.cleanup()
    except OSError:
        pass


def create_temp_dir() -> TemporaryDirectory:
    runtime_probe_path = RUNTIME_TEMP_DIR / ".write-test"

    try:
        runtime_probe_path.write_bytes(b"ok")
        runtime_probe_path.unlink(missing_ok=True)
    except OSError:
        return TemporaryDirectory(ignore_cleanup_errors=True)

    temp_dir = TemporaryDirectory(dir=RUNTIME_TEMP_DIR, ignore_cleanup_errors=True)
    probe_path = Path(temp_dir.name) / ".write-test"

    try:
        probe_path.write_bytes(b"ok")
        probe_path.unlink(missing_ok=True)
        return temp_dir
    except OSError:
        try:
            temp_dir.cleanup()
        except OSError:
            pass
        return TemporaryDirectory(ignore_cleanup_errors=True)


def save_upload(uploaded_file, temp_dir: TemporaryDirectory, prefix: str, suffix: str) -> tuple[TemporaryDirectory, Path]:
    input_path = Path(temp_dir.name) / f"{prefix}-{uuid.uuid4().hex}{suffix}"

    try:
        uploaded_file.save(input_path)
        return temp_dir, input_path
    except OSError:
        cleanup_temp_dir(temp_dir)

    fallback_dir = TemporaryDirectory(ignore_cleanup_errors=True)
    fallback_path = Path(fallback_dir.name) / f"{prefix}-{uuid.uuid4().hex}{suffix}"
    uploaded_file.stream.seek(0)
    uploaded_file.save(fallback_path)
    return fallback_dir, fallback_path


@app.get("/")
def index():
    return render_tool_page()


@app.get("/merge")
def merge_page():
    return render_tool_page(active_tool="merge")


@app.get("/split")
def split_page():
    return render_tool_page(active_tool="split")


@app.get("/compress")
def compress_page():
    return render_tool_page(active_tool="compress")


@app.get("/convert")
def convert_page():
    return render_tool_page(active_tool="convert")


@app.post("/compress")
def compress():
    
    uploaded_file = request.files.get("file")
    if not uploaded_file or uploaded_file.filename == "":
        return render_tool_error("Choose a PDF or image file first.", active_tool="compress", status=400)

    original_filename = uploaded_file.filename or ""
    print("=" * 50)
    print("Original filename:", repr(original_filename))
    print("Suffix:", repr(Path(original_filename).suffix.lower()))
    print("Allowed:", ALLOWED_EXTENSIONS)
    print("=" * 50)

    suffix = Path(original_filename).suffix.lower()
    print("ROUTE SUFFIX =", repr(suffix))

    if suffix not in ALLOWED_EXTENSIONS:
        return render_tool_error(
            "Unsupported file type. Use PDF, JPG, JPEG, PNG, or WEBP.",
            active_tool="compress",
        )

    validated_suffix = suffix

    filename = secure_filename(original_filename)
    if not filename:
        filename = f"upload{validated_suffix}"

    profile = request.form.get("profile", "balanced").lower()
    settings = CompressionSettings.from_profile(profile)

    print("CALLING compress_bytes WITH =", repr(validated_suffix))
    try:
        output_data, mimetype, original_size, compressed_size, output_suffix = compress_bytes(
            uploaded_file.read(),
            suffix,
            settings,
        )

    except CompressionError as exc:
        print("CompressionError:", repr(exc))
        return render_tool_error(
            str(exc),
            active_tool="compress",
            status=400,
        )

    except Exception as exc:
        import traceback

        traceback.print_exc()
        print("Exception:", repr(exc))

        return render_tool_error(
            "Something went wrong while compressing the file.",
            active_tool="compress",
            status=500,
        )
    download_stem = Path(filename).stem
    response = build_memory_download_response(
        output_data,
        mimetype,
        f"compressed-{download_stem}{output_suffix}",
    )
    savings = max(original_size - compressed_size, 0)
    response.headers["X-Original-Size"] = str(original_size)
    response.headers["X-Compressed-Size"] = str(compressed_size)
    response.headers["X-Bytes-Saved"] = str(savings)
    return response


@app.post("/merge")
def merge():
    uploaded_files = [file for file in request.files.getlist("files") if file and file.filename]
    if len(uploaded_files) < 2:
        return render_tool_error("Choose at least two PDF files to merge.", active_tool="merge", status=400)

    input_files: list[tuple[str, bytes]] = []

    try:
        for index, uploaded_file in enumerate(uploaded_files, start=1):
            filename = secure_filename(uploaded_file.filename)
            if not has_allowed_extension(filename, PDF_ONLY_EXTENSIONS):
                raise DocumentToolError("Merge accepts PDF files only.")

            input_files.append((filename or f"merge-{index:02d}.pdf", uploaded_file.read()))

        output_data = merge_pdf_bytes(input_files)
    except DocumentToolError as exc:
        return render_tool_error(str(exc), active_tool="merge", status=400)
    except Exception:
        return render_tool_error("Something went wrong while merging files.", active_tool="merge", status=500)

    return build_memory_download_response(output_data, "application/pdf", "merged-document.pdf")


@app.post("/split")
def split():
    uploaded_file = request.files.get("file")
    if not uploaded_file or uploaded_file.filename == "":
        return render_tool_error("Choose a PDF file to split first.", active_tool="split", status=400)

    filename = secure_filename(uploaded_file.filename)
    if not has_allowed_extension(filename, PDF_ONLY_EXTENSIONS):
        return render_tool_error("Split accepts PDF files only.", active_tool="split", status=400)

    ranges_text = request.form.get("ranges", "")
    output_mode = request.form.get("split_output", "zip").lower()
    try:
        data = uploaded_file.read()
        output_data, mimetype, download_name = split_pdf_bytes(data, Path(filename).stem, ranges_text, output_mode)
    except DocumentToolError as exc:
        return render_tool_error(str(exc), active_tool="split", status=400)
    except Exception:
        return render_tool_error("Something went wrong while splitting the PDF.", active_tool="split", status=500)

    return build_memory_download_response(output_data, mimetype, download_name)


@app.post("/split/page-count")
def split_page_count():
    uploaded_file = request.files.get("file")
    if not uploaded_file or uploaded_file.filename == "":
        return "Choose a PDF file first.", 400, {"Content-Type": "text/plain; charset=utf-8"}

    filename = secure_filename(uploaded_file.filename)
    if not has_allowed_extension(filename, PDF_ONLY_EXTENSIONS):
        return "Page preview accepts PDF files only.", 400, {"Content-Type": "text/plain; charset=utf-8"}

    try:
        page_count = get_pdf_page_count_bytes(uploaded_file.read())
    except DocumentToolError as exc:
        return str(exc), 400, {"Content-Type": "text/plain; charset=utf-8"}
    except Exception:
        return "Unable to preview this PDF.", 500, {"Content-Type": "text/plain; charset=utf-8"}

    return {"page_count": page_count}


@app.post("/convert")
def convert():
    uploaded_files = [file for file in request.files.getlist("file") if file and file.filename]
    if not uploaded_files:
        return render_tool_error("Choose a file to convert first.", active_tool="convert", status=400)

    convert_to = request.form.get("target", "pdf").lower()

    try:
        if convert_to == "pdf":
            image_files: list[tuple[str, bytes]] = []
            for index, uploaded_file in enumerate(uploaded_files, start=1):
                filename = secure_filename(uploaded_file.filename)
                if not has_allowed_extension(filename, IMAGE_ONLY_EXTENSIONS):
                    raise DocumentToolError("PDF conversion accepts JPG, JPEG, PNG, or WEBP images.")
                image_files.append((filename or f"image-{index:02d}.jpg", uploaded_file.read()))

            output_data = convert_image_files_to_pdf_bytes(image_files)
            download_name = "combined-images.pdf" if len(image_files) > 1 else f"{Path(image_files[0][0]).stem}.pdf"
            return build_memory_download_response(output_data, "application/pdf", download_name)
        elif convert_to == "jpg":
            uploaded_file = uploaded_files[0]
            if len(uploaded_files) != 1:
                raise DocumentToolError("JPG conversion accepts one PDF file only.")
            filename = secure_filename(uploaded_file.filename)
            if not has_allowed_extension(filename, PDF_ONLY_EXTENSIONS):
                raise DocumentToolError("JPG conversion accepts PDF files only.")
            input_data = uploaded_file.read()
            output_data = convert_pdf_to_jpg_zip_bytes(input_data, Path(filename).stem)
            return build_memory_download_response(output_data, "application/zip", f"{Path(filename).stem}-jpg.zip")
        else:
            raise DocumentToolError("Unsupported conversion option.")
    except DocumentToolError as exc:
        return render_tool_error(str(exc), active_tool="convert", status=400)
    except Exception:
        return render_tool_error("Something went wrong while converting the file.", active_tool="convert", status=500)


if __name__ == "__main__":
    app.run(debug=True)
