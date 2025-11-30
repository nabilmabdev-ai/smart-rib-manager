# app/services/banking.py
import re

# DELETED: MOROCCAN_BANKS dictionary (now in DB)

def normalize_rib(rib: str) -> str:
    if not rib: return ""
    return re.sub(r'\D', '', rib)

def sanitize_ocr_numbers(text: str) -> str:
    if not text: return ""
    text = text.upper()
    mapping = {
        'O': '0', 'D': '0', 'B': '8', 
        'I': '1', 'L': '1', 'S': '5', 'Z': '2'
    }
    for char, replacement in mapping.items():
        text = text.replace(char, replacement)
    return re.sub(r'\D', '', text)

def validate_moroccan_rib(rib: str, banks_dict: dict, ai_bank_name: str = None):
    """
    Validates RIB based on USER RULES:
    1. Must be 24 digits.
    2. First 3 digits MUST exist in banks_dict (Database).
    3. Mathematical Key check is DISABLED (Obsolete).
    """
    clean = normalize_rib(rib)
    
    # Try sanitizing if raw normalize didn't give digits
    if len(clean) != 24:
        clean = sanitize_ocr_numbers(rib)
    
    bank_name = "Banque Inconnue"
    bank_code_exists = False
    
    # 1. Check Bank Code against Database
    if len(clean) >= 3:
        code = clean[:3]
        if code in banks_dict:
            bank_name = banks_dict[code]['name']
            bank_code_exists = True
        elif ai_bank_name and len(ai_bank_name) > 2:
             # Just for display, but technically invalid if code not in DB
             bank_name = f"{ai_bank_name} (Code {code} inconnu)"

    # 2. Strict Validation Rule
    # Valid = Length is 24 AND Digits Only AND Bank Code matches DB
    is_valid = (len(clean) == 24 and clean.isdigit() and bank_code_exists)
    
    return {
        "isValid": is_valid,
        "bankName": bank_name,
        "normalized": clean,
        "keyCheck": True # Always True (Skipped)
    }

def get_bank_name(rib: str, banks_dict: dict, ai_bank_name: str = None) -> str:
    """Helper for templates"""
    if not rib: return ""
    # We do a quick check to get the name
    clean = normalize_rib(rib)
    if len(clean) >= 3:
        code = clean[:3]
        if code in banks_dict:
            return banks_dict[code]['name']
    
    if ai_bank_name: return ai_bank_name
    return ""