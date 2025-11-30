# app/services/ocr.py
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import json
import re
import google.generativeai as genai
from google.cloud import vision
from app.services.banking import sanitize_ocr_numbers

# Config
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google-credentials.json"
vision_client = vision.ImageAnnotatorClient()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

executor = ThreadPoolExecutor()

async def extract_text_from_image_bytes(content: bytes) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _sync_extract, content)

def _sync_extract(content: bytes) -> str:
    try:
        image = vision.Image(content=content)
        response = vision_client.text_detection(image=image)
        if response.text_annotations:
            return response.text_annotations[0].description
        return ""
    except Exception as e:
        print(f"Google Vision Error: {e}")
        return ""

async def parse_extracted_text(
    raw_text: str, 
    doc_type: str = "RIB", 
    known_banks_names: list = [],
    known_bank_codes: list = []
):
    """
    Uses Gemini to parse unstructured OCR text.
    """
    if not raw_text:
        return {}

    # Context strings
    banks_context = ", ".join(known_banks_names) if known_banks_names else "Attijariwafa, Banque Populaire, BMCE, CIH, etc."
    codes_context = ", ".join(known_bank_codes) if known_bank_codes else "007, 190, 230, etc."

    model = genai.GenerativeModel('gemini-2.0-flash') 

    prompt = ""

    if doc_type == "RIB":
        prompt = f"""
          You are an expert Data Entry Clerk for Moroccan Banking.
          
          TASK: Extract the 24-digit RIB Number, Bank Name, and Account Name.
          
          CRITICAL RULES FOR RIB CONSTRUCTION:
          1. **TARGET:** A Moroccan RIB is STRICTLY 24 digits long.
          
          2. **SCENARIO A (IBAN Priority):**
             If you see an IBAN (starts with 'MA'), the RIB is digits 5 to 28 of the IBAN. 
             Extract this sequence.
          
          3. **SCENARIO B (Tabular):**
             The RIB is often split into 4 boxes: [Code Banque(3)] [Code Ville(3)] [N° Compte(16)] [Clé(2)].
             You MUST concatenate them.
             *Example:* "230" + "780" + "3918...1700" + "49" -> "2307803918...170049"
             
          4. **VALIDATION:**
             - The result MUST start with one of these valid Bank Codes: {codes_context}.
             - Remove spaces, dashes, and non-digit characters.

          5. **BANK NAME:** Map the logo/text to: {banks_context}.

          Output strictly valid JSON:
          {{
            "rib": "string_24_digits_only",
            "firstName": "string_or_null",
            "lastName": "string_or_null",
            "bankName": "string_or_null" 
          }}

          OCR DATA:
          {raw_text[:5000]}
        """
    
    elif doc_type == "CIN":
        prompt = f"""
          You are an expert HR Assistant in Morocco. 
          Analyze the provided OCR text from a Moroccan National ID (CIN).
          Extract CIN Number, First Name, Last Name, Birth Date (DD/MM/YYYY), Validity Date (DD/MM/YYYY), Address.
          
          Output strictly valid JSON:
          {{
            "cin_number": "string_or_null",
            "first_name": "string_or_null",
            "last_name": "string_or_null",
            "birth_date": "string_or_null",
            "validity_date": "string_or_null",
            "address": "string_or_null"
          }}

          OCR DATA:
          {raw_text[:5000]}
        """

    try:
        response = await model.generate_content_async(prompt)
        text_response = response.text.strip()
        
        if text_response.startswith("```json"):
            text_response = text_response[7:-3]
        elif text_response.startswith("```"):
            text_response = text_response[3:-3]

        data = json.loads(text_response)
        
        if doc_type == "RIB":
            raw_rib = str(data.get("rib") or "")
            clean_rib = sanitize_ocr_numbers(raw_rib)

            # --- PYTHON POST-PROCESSING (Safety Net) ---
            
            # STRATEGY 1: IBAN EXTRACTION (Highest Priority)
            # Looks for 'MA' followed by 2 digits, then captures the next 24 digits/spaces
            if len(clean_rib) != 24:
                iban_match = re.search(r'MA\s*\d{2}\s*((?:\d\s*){24})', raw_text, re.IGNORECASE)
                if iban_match:
                    # Extract the group and remove spaces
                    potential_rib = re.sub(r'\D', '', iban_match.group(1))
                    if len(potential_rib) == 24:
                        clean_rib = potential_rib
            
            # STRATEGY 2: BANK CODE SEARCH (Fallback)
            # If still not 24 digits, try finding a valid code inside the string
            if len(clean_rib) != 24:
                found_rib = None
                for code in known_bank_codes:
                    idx = clean_rib.find(code)
                    if idx != -1:
                        candidate = clean_rib[idx : idx + 24]
                        if len(candidate) == 24:
                            found_rib = candidate
                            break
                if found_rib:
                    clean_rib = found_rib
            
            return {
                "rib": clean_rib,
                "firstName": (data.get("firstName") or "").upper(),
                "lastName": (data.get("lastName") or "").upper(),
                "bankName": (data.get("bankName") or "").strip(),
                "raw_text": raw_text[:3000]
            }
        
        elif doc_type == "CIN":
            return {
                "cin_number": (data.get("cin_number") or "").replace(" ", "").upper(),
                "first_name": (data.get("first_name") or "").upper(),
                "last_name": (data.get("last_name") or "").upper(),
                "birth_date": data.get("birth_date"),
                "validity_date": data.get("validity_date"),
                "address": (data.get("address") or "").strip(),
                "raw_text": raw_text[:3000]
            }
        return {}
    except Exception as e:
        print(f"Gemini Error ({doc_type}): {e}")
        if doc_type == "RIB":
            return {"rib": "", "firstName": "", "lastName": "", "bankName": "", "raw_text": f"Error: {str(e)}"}
        else:
            return {"cin_number": "", "first_name": "", "last_name": "", "raw_text": f"Error: {str(e)}"}

# Helper function (Restored)
def validate_extraction_in_source(extracted_value: str, raw_text: str) -> bool:
    if not extracted_value: return False
    clean_extracted = re.sub(r'[^a-zA-Z0-9]', '', extracted_value).upper()
    clean_raw = re.sub(r'[^a-zA-Z0-9]', '', raw_text).upper()
    return clean_extracted in clean_raw