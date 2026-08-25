"""Utilities for extracting content from source documents."""

from os import PathLike
from typing import BinaryIO

import pymupdf


def extract_text_from_pdf(pdf_file: str | PathLike[str] | BinaryIO) -> str:
    """Return the text layer of a PDF in page order."""
    if hasattr(pdf_file, "read"):
        document = pymupdf.open(stream=pdf_file.read(), filetype="pdf")
    else:
        document = pymupdf.open(pdf_file)

    with document:
        return "".join(page.get_text() for page in document)
