import re
from dateutil import parser
import dateparser
import fitz  # PyMuPDF for PDFs
import docx  # python-docx for Word
import pytesseract
from PIL import Image
import os
import platform

# Configure Tesseract path on Windows if not already set
if platform.system().lower().startswith("win"):
    default_tess = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
    if os.path.exists(default_tess) and not os.environ.get("TESSDATA_PREFIX"):
        try:
            pytesseract.pytesseract.tesseract_cmd = default_tess
        except Exception:
            pass

def extract_text_from_file(file_path):
    """
    Extracts text from PDF, DOCX, or image files.
    Returns extracted text as a string.
    """
    text = ""

    if file_path.endswith(".pdf"):
        doc = fitz.open(file_path)
        for page in doc:
            text += page.get_text("text")

    elif file_path.endswith(".docx"):
        doc = docx.Document(file_path)
        for para in doc.paragraphs:
            text += para.text + "\n"

    elif file_path.lower().endswith((".png", ".jpg", ".jpeg")):
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img)

    else:
        raise ValueError("Unsupported file format. Please upload PDF, DOCX, or Image.")

    return text.strip()


def normalize_time(text):
    dt = dateparser.parse(text, settings={'TIMEZONE': 'Asia/Kolkata', 'RETURN_AS_TIMEZONE_AWARE': False})
    if dt and dt.time():
        return dt.strftime("%I:%M %p")
    return None


def extract_event_details(text):
    """
    Extract potential deadline/event date and time from text with heuristics.
    - Prioritize phrases around 'deadline', 'last date', 'by', 'before', 'submission', 'register by'
    - Fallback to the first future-looking datetime in the text
    Also extract a venue/location if present.
    Returns (date_str, time_str, venue)
    """
    date_str, time_str, venue = None, None, None

    # 1) Try to find explicit deadline-like phrases with a small window around them
    deadline_patterns = [
        r"deadline[^\w]{0,10}([^.\n]{0,80})",
        r"last date[^\w]{0,10}([^.\n]{0,80})",
        r"register by[^\w]{0,10}([^.\n]{0,80})",
        r"submit by[^\w]{0,10}([^.\n]{0,80})",
        r"before[^\w]{0,10}([^.\n]{0,80})",
        r"by[^\w]{0,10}([^.\n]{0,80})",
        r"extended\s+(till|until|to)[^\w]{0,10}([^.\n]{0,80})",
    ]

    for pat in deadline_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if not m:
            continue
        context = m.group(0)
        # extend context a bit to the right to capture date/time tokens
        start = m.start()
        end = min(len(text), m.end() + 120)
        snippet = text[start:end]
        dt = dateparser.parse(
            snippet,
            settings={
                'PREFER_DATES_FROM': 'future',
                'DATE_ORDER': 'DMY',
                'TIMEZONE': 'Asia/Kolkata',
                'RETURN_AS_TIMEZONE_AWARE': False
            }
        )
        if dt:
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%I:%M %p") if dt.time() else None
            break

    # 2) Fallback: parse from entire text
    if not date_str:
        dt = dateparser.parse(
            text,
            settings={
                'PREFER_DATES_FROM': 'future',
                'DATE_ORDER': 'DMY',
                'TIMEZONE': 'Asia/Kolkata',
                'RETURN_AS_TIMEZONE_AWARE': False
            }
        )
        if dt:
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%I:%M %p") if dt.time() else None

    # 3) Venue/location
    venue_match = re.search(r"(at|venue|place)[:\- ]+([^\n,]+)", text, re.IGNORECASE)
    venue = venue_match.group(2).strip() if venue_match else None

    return date_str, time_str, venue
