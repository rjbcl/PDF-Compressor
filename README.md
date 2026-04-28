# PDF-Compressor
This project is for compressing official documents of RJBCL

# PDF and Image Compressor

A small Flask app for handling everyday office PDF tasks locally.

## Features

- Merge multiple PDF files into one combined document
- Split a PDF by any page numbers or ranges and download separate PDFs in a ZIP archive
- Extract selected PDF pages and merge them into one new PDF
- Compress PDFs through page re-encoding for scanned or image-heavy documents
- Compress JPG, PNG, and WEBP images with resize and optimization support
- Convert images to PDF
- Convert PDF pages to JPG files in a ZIP archive
- Choose from three compression profiles: `small`, `balanced`, and `quality`
- Use a simple browser-based upload form

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Notes

- PDF compression rebuilds each page as an optimized image. This usually shrinks scanned PDFs well, but selectable text and vector detail may be flattened.
- PDF splitting uses page ranges like `1, 3, 5-8, 12` and can return separate PDFs in one ZIP file or one merged PDF of the selected pages.
- JPG and WEBP files are exported as optimized JPG files to get stronger size reduction.
- PNG files stay as PNG and are palette-optimized where possible.
- PDF to JPG conversion exports one JPG per page inside a ZIP file.
