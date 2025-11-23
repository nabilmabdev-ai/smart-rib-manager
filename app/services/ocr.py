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
    # Run the blocking Vision call in a separate thread
    return await loop.run_in_executor(executor, _sync_extract, content)

def _sync_extract(content: bytes) -> str:
    """Wrapper for the blocking Google Vision call"""
    try:
        image = vision.Image(content=content)
        response = vision_client.text_detection(image=image)
        if response.text_annotations:
            return response.text_annotations[0].description
        return ""
    except Exception as e:
        print(f"Google Vision Error: {e}")
        return ""

async def parse_extracted_text(raw_text: str, doc_type: str = "RIB"):
    """
    Uses Gemini to parse unstructured OCR text into structured JSON.
    Supports doc_type: 'RIB' or 'CIN'.
    """
    if not raw_text:
        return {}

    print(f"🧠 Sending to Gemini ({doc_type})...")
    
    # Using 'gemini-2.0-flash' or 'gemini-1.5-flash' is recommended for speed/cost
    # If not available, fallback to 'gemini-pro'
    model = genai.GenerativeModel('gemini-2.0-flash') 

    prompt = ""

    if doc_type == "RIB":
        prompt = f"""
          You are an expert Data Entry Clerk for Moroccan Banking.
          Analyze the provided OCR text. Extract:
          1. The Account Holder's Name.
          2. The RIB (24 digits).
          3. The Bank Name (Look at logos, headers, or text like 'Banque Populaire', 'CIH', 'Crédit Agricole').
          
          Context:
          - RIB: 24 digits. Correct common typos (O->0, B->8, S->5).
          - Names: Handle prefixes like 'AIT', 'BEN', 'EL'.
          
          Output strictly valid JSON:
          {{
            "rib": "string_or_null",
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
          Analyze the provided OCR text from a Moroccan National ID (CIN / Carte d'Identité Nationale).
          
          Extract:
          1. CIN Number (Numéro de CIN): Usually 1-2 letters followed by numbers (e.g., BJ42291, A40020, I123456).
          2. First Name & Last Name: Convert to UPPERCASE.
          3. Date of Birth (Date de Naissance): Format DD/MM/YYYY.
          4. Validity Date (Valable jusqu'au): Format DD/MM/YYYY.
          5. Address (Adresse): Usually found on the back of the card. If found, extract it.

          Context:
          - Dates: Ensure standard DD/MM/YYYY format (e.g., 01/01/1990).
          - Noise: Ignore watermarks or background text.

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
        
        # Clean markdown code blocks if present
        if text_response.startswith("```json"):
            text_response = text_response[7:-3]
        elif text_response.startswith("```"):
            text_response = text_response[3:-3]

        data = json.loads(text_response)
        
        # Post-Processing based on type
        if doc_type == "RIB":
            return {
                "rib": sanitize_ocr_numbers(str(data.get("rib") or "")),
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
        # Return empty structure with error in raw_text for debugging
        if doc_type == "RIB":
            return {"rib": "", "firstName": "", "lastName": "", "bankName": "", "raw_text": f"Error: {str(e)}"}
        else:
            return {"cin_number": "", "first_name": "", "last_name": "", "raw_text": f"Error: {str(e)}"}

def validate_extraction_in_source(extracted_value: str, raw_text: str) -> bool:
    """
    Generic validation: Ensure the critical digits/chars actually exist in the source 
    to prevent AI hallucination.
    """
    if not extracted_value:
        return False
        
    # Remove all non-alphanumeric chars for comparison
    clean_extracted = re.sub(r'[^a-zA-Z0-9]', '', extracted_value).upper()
    clean_raw = re.sub(r'[^a-zA-Z0-9]', '', raw_text).upper()
    
    # Strict check: The sequence must exist
    return clean_extracted in clean_raw