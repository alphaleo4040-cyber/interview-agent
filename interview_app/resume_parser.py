# Re-export from core.resume_parser
from core.resume_parser import (
    POPULAR_JOB_DESCRIPTIONS,
    extract_text_from_pdf,
    extract_text_from_docx,
    parse_resume_file,
)

__all__ = [
    "POPULAR_JOB_DESCRIPTIONS",
    "extract_text_from_pdf",
    "extract_text_from_docx",
    "parse_resume_file",
]
