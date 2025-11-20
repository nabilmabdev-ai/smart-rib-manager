# app/services/ocr.py
import os
import json
import io
import google.generativeai as genai
from google.cloud import vision
from app.services.banking import sanitize_ocr_numbers

# Config
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google-credentials.json"
vision_client = vision.ImageAnnotatorClient()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def extract_text_from_image_bytes(content: bytes) -> str:
    """Google Vision OCR"""
    try:
        image = vision.Image(content=content)
        response = vision_client.text_detection(image=image)
        if response.text_annotations:
            return response.text_annotations[0].description
        return ""
    except Exception as e:
        print(f"Google Vision Error: {e}")
        return ""

async def parse_extracted_text(raw_text: str):
    if not raw_text:
        return {"rib": "", "firstName": "", "lastName": "", "bankName": "", "raw_text": ""}

    print("🧠 Sending to Gemini...")
    
    model = genai.GenerativeModel('gemini-2.5-pro') # Use gemini-pro or 1.5-flash

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

    try:
        response = model.generate_content(prompt)
        text_response = response.text.strip()
        
        # Clean markdown
        if text_response.startswith("```json"):
            text_response = text_response[7:-3]
        elif text_response.startswith("```"):
            text_response = text_response[3:-3]

        data = json.loads(text_response)
        
        return {
            "rib": sanitize_ocr_numbers(str(data.get("rib") or "")),
            "firstName": (data.get("firstName") or "").upper(),
            "lastName": (data.get("lastName") or "").upper(),
            "bankName": (data.get("bankName") or "").strip(), # Capture Bank Name
            "raw_text": raw_text[:3000]
        }
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {
            "rib": "", "firstName": "", "lastName": "", "bankName": "",
            "raw_text": raw_text[:2000] + f"\n[AI Failed: {str(e)}]"
        }

def validate_extraction_in_source(extracted_rib: str, raw_text: str) -> bool:
    """
    Ensure the digits of the RIB actually exist in the source document
    to prevent AI hallucination.
    """
    import re
    # Remove all non-digits from raw text
    clean_raw = re.sub(r'\D', '', raw_text)
    
    # Check if the sequence exists (allowing for small OCR gaps is complex, 
    # but strict existence is safer for banking)
    return extracted_rib in clean_raw