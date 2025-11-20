# app/services/banking.py
import re

MOROCCAN_BANKS = {
    '007': {'name': 'Attijariwafa Bank'},
    '011': {'name': 'BMCE Bank of Africa'},
    '013': {'name': 'BMCI (BNP Paribas)'},
    '021': {'name': 'Crédit du Maroc'},
    '022': {'name': 'Société Générale Maroc'},
    '023': {'name': 'BMCI'},
    '031': {'name': 'Crédit Agricole du Maroc'},
    '028': {'name': 'Citibank Maghreb'},
    '101': {'name': 'Banque Populaire (Régional)'},
    '127': {'name': 'Banque Populaire'},
    '145': {'name': 'Banque Populaire'},
    '157': {'name': 'Banque Populaire (BCP)'},
    '190': {'name': 'Banque Populaire'},
    '225': {'name': 'Al Barid Bank'}, # <--- Added this code
    '230': {'name': 'CIH Bank'},
    '310': {'name': 'Trésorerie Générale'},
    '002': {'name': 'Bank Al-Maghrib'},
    '005': {'name': 'Arab Bank'},
}

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

def verify_rib_key(rib: str) -> bool:
    """
    Validates the Moroccan RIB Key (Clé RIB) using the Modulo 97 algorithm.
    Formula: Key = 97 - ( (89*Bank + 15*City + 3*Acct) % 97 )
    """
    try:
        if len(rib) != 24 or not rib.isdigit():
            return False

        bank_code = int(rib[0:3])
        city_code = int(rib[3:6])
        account_num = int(rib[6:22])
        key_provided = int(rib[22:24])

        # Standard verification math
        # We treat the first 22 digits as a large integer for the remainder check
        # Or use the specific coefficient method:
        remainder = (89 * bank_code + 15 * city_code + 3 * account_num) % 97
        key_calculated = 97 - remainder

        return key_calculated == key_provided
    except:
        return False

# Update your validation function to use this:
def validate_moroccan_rib(rib: str, ai_bank_name: str = None):
    """
    Validates RIB and resolves Bank Name using Hybrid approach (Code vs AI).
    """
    clean = normalize_rib(rib)
    
    # Retry cleaning
    if len(clean) != 24:
        clean = sanitize_ocr_numbers(rib)
    
    bank_name = "Banque Inconnue"
    
    # 1. Try Deterministic Lookup (RIB Code)
    if len(clean) >= 3:
        code = clean[:3]
        if code in MOROCCAN_BANKS:
            bank_name = MOROCCAN_BANKS[code]['name']
        # 2. Smart Fallback: If code is unknown but AI saw a name, use AI
        elif ai_bank_name and len(ai_bank_name) > 2:
             bank_name = f"{ai_bank_name} (Détecté par IA)"

    # NEW: Mathematical Check
    math_valid = False
    if len(clean) == 24:
        math_valid = verify_rib_key(clean)
    
    return {
        "isValid": math_valid, # Use the math result, not just length
        "bankName": bank_name,
        "normalized": clean,
        "keyCheck": math_valid
    }

def get_bank_name(rib: str, ai_bank_name: str = None) -> str:
    if not rib:
        return ""
    result = validate_moroccan_rib(rib, ai_bank_name)
    if result['bankName'] == "Banque Inconnue":
        return ""
    return result['bankName']