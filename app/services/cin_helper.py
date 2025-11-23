# app/services/cin_helper.py
import re
from datetime import datetime

def clean_cin_number(text: str) -> str:
    """
    Standardizes a Moroccan CIN number.
    Removes spaces, dashes, and ensures uppercase.
    Example: "BJ 42-99" -> "BJ4299"
    """
    if not text: 
        return ""
    # Remove non-alphanumeric characters except standard letters and digits
    return re.sub(r'[^a-zA-Z0-9]', '', text).upper()

def parse_date(date_str: str):
    """
    Attempts to parse a date string in DD/MM/YYYY format.
    Returns a python date object or None.
    """
    if not date_str: 
        return None
    
    # Clean common OCR noise like 'O' instead of '0' or spaces
    date_str = date_str.replace('O', '0').replace('o', '0').strip()
    
    try:
        # Try standard format
        return datetime.strptime(date_str, "%d/%m/%Y").date()
    except ValueError:
        try:
            # Try format with dots
            return datetime.strptime(date_str, "%d.%m.%Y").date()
        except ValueError:
            try:
                # Try format with hyphens
                return datetime.strptime(date_str, "%d-%m-%Y").date()
            except ValueError:
                return None

def validate_cin(data: dict) -> str:
    """
    Analyzes extracted CIN data and determines its status.
    Returns: 'VALID', 'EXPIRED', 'ERROR', 'SUSPICIOUS'
    """
    
    # 1. Get and Clean Data
    cin_num = clean_cin_number(data.get("cin_number"))
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    validity_str = data.get("validity_date")

    # 2. Check CIN Syntax (Moroccan Standard)
    # Must be 1-2 letters followed by 3-6 digits (e.g., A123, BJ452200)
    # Regex: ^[A-Z]{1,2}\d{3,6}$
    if not cin_num:
        return "ERROR"
    
    if not re.match(r'^[A-Z]{1,2}\d{3,8}$', cin_num):
        # If it doesn't look like a CIN at all
        return "ERROR"

    # 3. Check for Missing Names
    if not first_name or not last_name or len(last_name) < 2:
        return "SUSPICIOUS"

    # 4. Check Expiry Date (Critical for HR)
    if validity_str:
        expiry_date = parse_date(validity_str)
        if expiry_date:
            # Check if expired
            if expiry_date < datetime.now().date():
                return "EXPIRED"
            
            # Check for suspicious dates (e.g., year 1900 or year 2099)
            if expiry_date.year < 2020 or expiry_date.year > 2040:
                 # While not strictly "Error", old dates might be OCR fail 
                 # or very old cards. We'll mark VALID but let human check,
                 # unless it's clearly in the past (already caught above).
                 pass
        else:
            # Date exists but couldn't be parsed
            return "SUSPICIOUS"
    else:
        # No validity date found (common on old cards or bad OCR)
        return "SUSPICIOUS"

    return "VALID"