# PDF-Compressor
This project if for compressing official documnents of RJBCL

# PDF and Image Compressor

A small Flask app for compressing PDF and image files locally.

## Features

- Compress PDFs through page re-encoding for scanned or image-heavy documents
- Compress JPG, PNG, and WEBP images with resize and optimization support
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
- JPG and WEBP files are exported as optimized JPG files to get stronger size reduction.
- PNG files stay as PNG and are palette-optimized where possible.
