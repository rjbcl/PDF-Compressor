from __future__ import annotations

from pathlib import Path

from pdf_tools import merge_pdfs


def merge_documents(input_paths: list[Path], output_path: Path):
    return merge_pdfs(input_paths, output_path)
