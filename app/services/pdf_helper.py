# app/services/pdf_helper.py
import io
from pypdf import PdfReader
from pdf2image import convert_from_bytes

def parse_pdf_text(file_bytes: bytes) -> str:
    """
    Extracts raw text from a digital PDF using pypdf.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""

def convert_pdf_to_image(file_bytes: bytes):
    """
    Converts the first page of a PDF to a PIL Image.
    Used when text extraction fails (scanned PDFs).
    """
    try:
        # Convert first page only to save resources
        # Note: On Windows, ensure poppler_path is configured if not in PATH
        images = convert_from_bytes(file_bytes, first_page=1, last_page=1)
        if images:
            return images[0]
        return None
    except Exception as e:
        print(f"Error converting PDF to image: {e}")
        return None
