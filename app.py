from __future__ import annotations

import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename

from compressor import CompressionError, CompressionSettings, compress_file


BASE_DIR = Path(__file__).resolve().parent
RUNTIME_TEMP_DIR = BASE_DIR / ".tmp"

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

RUNTIME_TEMP_DIR.mkdir(exist_ok=True)


def is_allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/compress")
def compress():
    uploaded_file = request.files.get("file")
    if not uploaded_file or uploaded_file.filename == "":
        return render_template("index.html", error="Choose a PDF or image file first."), 400

    filename = secure_filename(uploaded_file.filename)
    if not is_allowed_file(filename):
        return (
            render_template(
                "index.html",
                error="Unsupported file type. Use PDF, JPG, JPEG, PNG, or WEBP.",
            ),
            400,
        )

    profile = request.form.get("profile", "balanced").lower()
    settings = CompressionSettings.from_profile(profile)

    suffix = Path(filename).suffix.lower()
    token = uuid.uuid4().hex

    temp_dir = TemporaryDirectory(dir=RUNTIME_TEMP_DIR, ignore_cleanup_errors=True)
    temp_path = Path(temp_dir.name)
    input_path = temp_path / f"upload-{token}{suffix}"
    output_path = temp_path / f"compressed-{token}{suffix}"
    uploaded_file.save(input_path)

    try:
        result = compress_file(input_path, output_path, settings)
    except CompressionError as exc:
        temp_dir.cleanup()
        return render_template("index.html", error=str(exc)), 400
    except Exception:
        temp_dir.cleanup()
        return (
            render_template(
                "index.html",
                error="Something went wrong while compressing the file.",
            ),
            500,
        )

    download_name = f"compressed-{filename}"
    savings = max(result.original_size - result.compressed_size, 0)
    response = send_file(
        result.output_path,
        as_attachment=True,
        download_name=download_name,
        mimetype=result.mimetype,
        etag=False,
        last_modified=None,
        max_age=0,
    )
    response.headers["X-Original-Size"] = str(result.original_size)
    response.headers["X-Compressed-Size"] = str(result.compressed_size)
    response.headers["X-Bytes-Saved"] = str(savings)
    response.call_on_close(temp_dir.cleanup)
    return response


if __name__ == "__main__":
    app.run(debug=True)
