# app/routers/ribs.py

import os
import shutil
import io
from typing import List
from fastapi import APIRouter, Depends, UploadFile, File, Form, Request, HTTPException, Response
import pandas as pd
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.database import get_session
from app import crud
from app.services import pdf_helper, ocr, banking
from app.auth import require_user, require_admin, require_operator
from app.models import EmployeeRib

# --- SETUP ---
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Note: On n'utilise plus de variable globale pour les banques. 
# On passe 'banks_dict' au template à chaque fois.

def calculate_period_stats(ribs_list, banks_dict):
    """
    Calcule les stats en utilisant le dictionnaire des banques passé en paramètre.
    """
    stats = {
        "total_files": len(ribs_list),
        "valid_ribs": 0,
        "discrepancies": 0,
        "bank_distribution": {}
    }
    
    for r in ribs_list:
        # Check Status
        if r.status in ["SUCCESS", "DUPLICATE"]:
            stats["valid_ribs"] += 1
            
            # Resolve Bank Name using DB dict
            b_name = banking.get_bank_name(r.rib, banks_dict, r.ai_bank_name)
            if b_name:
                stats["bank_distribution"][b_name] = stats["bank_distribution"].get(b_name, 0) + 1
        
        elif r.status in ["ERROR", "SUSPICIOUS"]:
            stats["discrepancies"] += 1
            
    # Sort banks by count descending
    stats["bank_distribution"] = dict(
        sorted(stats["bank_distribution"].items(), key=lambda item: item[1], reverse=True)
    )
    
    return stats

# --- ROUTES ---

@router.get("/", response_class=HTMLResponse)
async def read_root(
    request: Request, 
    db: Session = Depends(get_session),
    user: dict = Depends(require_user)
):
    periods = crud.get_periods(db)
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "periods": periods, 
        "user": user 
    })

@router.post("/period", response_class=HTMLResponse)
async def create_period_route(
    request: Request, 
    name: str = Form(...), 
    db: Session = Depends(get_session),
    user: dict = Depends(require_admin)
):
    crud.create_period(db, name)
    periods = crud.get_periods(db)
    return templates.TemplateResponse("partials/period_list.html", {
        "request": request, "periods": periods, "user": user
    })

@router.post("/period/{period_id}/toggle_lock")
async def toggle_period_lock(
    request: Request,
    period_id: str,
    db: Session = Depends(get_session),
    user: dict = Depends(require_admin)
):
    period = db.get(crud.Period, period_id)
    if period:
        period.is_locked = not period.is_locked
        db.add(period)
        db.commit()
        db.refresh(period)
    
    # Récupérer les banques pour les stats
    banks_dict = crud.get_banks_as_dict(db)
    stats = calculate_period_stats(period.ribs, banks_dict)
    
    return templates.TemplateResponse("period_detail.html", {
        "request": request, 
        "period": period,
        "stats": stats,
        "user": user,
        "banks_dict": banks_dict # Important pour l'affichage
    })

@router.get("/period/{period_id}", response_class=HTMLResponse)
async def read_period(
    request: Request, 
    period_id: str, 
    db: Session = Depends(get_session),
    user: dict = Depends(require_user)
):
    period = crud.get_period_by_id(db, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Period not found")
        
    # Récupérer les banques
    banks_dict = crud.get_banks_as_dict(db)
    stats = calculate_period_stats(period.ribs, banks_dict) 
    
    return templates.TemplateResponse("period_detail.html", {
        "request": request, 
        "period": period,
        "stats": stats,
        "user": user,
        "banks_dict": banks_dict
    })

# --- UPLOAD ---

@router.post("/period/{period_id}/upload")
async def upload_files(
    request: Request,
    period_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_session),
    user: dict = Depends(require_operator)
):
    period = crud.get_period_by_id(db, period_id)
    if period.is_locked:
        raise HTTPException(status_code=400, detail="This period is closed. Ask Admin to open it.")

    # 1. Fetch Banks Context for AI and Validation
    banks_list = crud.get_all_banks(db)
    banks_names = [b.name for b in banks_list] # Pour l'IA
    bank_codes = [b.code for b in banks_list] # Pour l'IA
    banks_dict = {b.code: {'name': b.name} for b in banks_list} # Pour la validation

    results = []
    
    for file in files:
        try:
            safe_name = f"{period_id}_{file.filename.replace(' ', '_')}"
            file_path = os.path.join(UPLOAD_DIR, safe_name)
            content = await file.read()
            with open(file_path, "wb") as f: f.write(content)
            
            raw_text = ""
            if file.content_type == "application/pdf":
                raw_text = pdf_helper.parse_pdf_text(content)
                if not raw_text or len(raw_text.strip()) < 50:
                    img = pdf_helper.convert_pdf_to_image(content)
                    if img:
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format='JPEG')
                        raw_text = await ocr.extract_text_from_image_bytes(img_byte_arr.getvalue())
            else:
                raw_text = await ocr.extract_text_from_image_bytes(content)

            # 2. AI Parsing with Bank Context
            parsed_data = await ocr.parse_extracted_text(raw_text, doc_type="RIB", known_banks_names=banks_names, known_bank_codes=bank_codes)
            
            status = "SUCCESS" if parsed_data["rib"] else "ERROR"

            # 3. Validation Logic (SIMPLIFIED)
            if parsed_data["rib"]: # Only proceed if AI returned a RIB
                val_res = banking.validate_moroccan_rib(parsed_data["rib"], banks_dict, parsed_data["bankName"])
                
                if val_res["isValid"]:
                    # Valid Length + Valid Bank Code (from DB)
                    status = "SUCCESS"
                    # Check for duplicates if still SUCCESS
                    if crud.check_duplicate_rib(db, period_id, parsed_data["rib"]):
                        status = "DUPLICATE"
                    # Check source consistency if still SUCCESS
                    elif not ocr.validate_extraction_in_source(parsed_data["rib"], raw_text):
                        status = "SUSPICIOUS"
                else:
                    # Invalid Length OR Invalid Bank Code
                    # No longer doing checksum check.
                    status = "ERROR"
            else:
                # AI did not return a RIB
                status = "ERROR"

            rib_entry = crud.create_rib_entry(db, {
                "period_id": period_id,
                "file_name": safe_name,
                "rib": parsed_data["rib"],
                "first_name": parsed_data["firstName"],
                "last_name": parsed_data["lastName"],
                "ai_bank_name": parsed_data["bankName"],
                "raw_text": parsed_data["raw_text"],
                "status": status
            })
            results.append(rib_entry)
            
        except Exception as e:
            print(f"Error: {e}")
            err = crud.create_rib_entry(db, {
                "period_id": period_id,
                "file_name": file.filename,
                "raw_text": f"Error: {str(e)}",
                "status": "ERROR"
            })
            results.append(err)

    period = crud.get_period_by_id(db, period_id)
    stats = calculate_period_stats(period.ribs, banks_dict)
    
    return templates.TemplateResponse("partials/upload_result.html", {
        "request": request, 
        "results": results, 
        "stats": stats,
        "banks_dict": banks_dict # Pass dict to partials
    })


@router.get("/rib/{rib_id}/modal", response_class=HTMLResponse)
async def get_edit_modal(request: Request, rib_id: str, db: Session = Depends(get_session), user: dict = Depends(require_user)):
    rib = db.get(crud.EmployeeRib, rib_id)
    if not rib:
        raise HTTPException(status_code=404, detail="RIB not found")
    return templates.TemplateResponse("partials/modal_edit.html", {"request": request, "rib": rib, "user": user})

@router.post("/rib/{rib_id}/update", response_class=HTMLResponse)
async def update_rib(
    request: Request, 
    rib_id: str, 
    first_name: str = Form(""), 
    last_name: str = Form(""), 
    rib: str = Form(""), 
    db: Session = Depends(get_session),
    user: dict = Depends(require_operator)
):
    rib_entry = db.get(EmployeeRib, rib_id)
    if not rib_entry:
        raise HTTPException(status_code=404, detail="RIB not found")
        
    # Block edits if period is locked
    if rib_entry.period.is_locked:
        # OLD: detail="Period is locked"
        # NEW:
        raise HTTPException(
            status_code=400, 
            detail="Action refusée : Ce dossier est verrouillé. Demandez à un Admin de le réouvrir."
        )

    # Fetch banks for validation
    banks_dict = crud.get_banks_as_dict(db)

    # --- FIX: Define clean_rib ---
    clean_rib = banking.normalize_rib(rib)
    # -----------------------------

    # --- UPDATED MANUAL VALIDATION ---
    new_status = "SUCCESS"
    
    # 1. Check Length (24)
    if len(clean_rib) != 24:
        new_status = "ERROR"
    
    # 2. Check Bank Code (Must exist in DB)
    elif clean_rib[:3] not in banks_dict:
        new_status = "ERROR" 
        
    # 3. Check Duplicates (Ignoring self)
    elif crud.check_duplicate_rib(db, rib_entry.period_id, clean_rib) and clean_rib != rib_entry.rib:
        new_status = "DUPLICATE"

    rib_entry.first_name = first_name.upper()
    rib_entry.last_name = last_name.upper()
    rib_entry.rib = clean_rib
    rib_entry.status = new_status
    rib_entry.is_manually_corrected = True
    
    db.add(rib_entry)
    db.commit()
    db.refresh(rib_entry)
    
    return templates.TemplateResponse("partials/rib_row.html", {
        "request": request, 
        "rib": rib_entry,
        "banks_dict": banks_dict
    })

@router.post("/rib/{rib_id}/retry_ai", response_class=HTMLResponse)
async def retry_rib_ai(
    request: Request,
    rib_id: str,
    db: Session = Depends(get_session),
    user: dict = Depends(require_operator)
):
    print(f"\n--- DEBUG RETRY START: {rib_id} ---")
    
    # 1. Get the RIB entry
    rib_entry = db.get(EmployeeRib, rib_id)
    if not rib_entry:
        print("❌ RIB non trouvé dans la DB.")
        raise HTTPException(status_code=404, detail="RIB not found")
    
    # DEBUG: Check Text Presence
    text_len = len(rib_entry.raw_text) if rib_entry.raw_text else 0
    print(f"📊 Texte actuel en DB: {text_len} caractères.")
    if text_len > 0:
        print(f"📝 Début du texte: {rib_entry.raw_text[:50]}...")
    else:
        print("⚠️ Le champ raw_text est vide ou None.")

    # 2. LOGIC: Fallback to Disk if Text is missing ( < 20 chars )
    if text_len < 20:
        print(f"🔄 Texte insuffisant. Tentative de relecture du fichier: {rib_entry.file_name}")
        file_path = os.path.join(UPLOAD_DIR, rib_entry.file_name)
        
        if os.path.exists(file_path):
            try:
                with open(file_path, "rb") as f: content = f.read()
                
                # Re-OCR Logic
                raw_text = ""
                if rib_entry.file_name.lower().endswith(".pdf"):
                    raw_text = pdf_helper.parse_pdf_text(content)
                    if not raw_text or len(raw_text.strip()) < 50:
                        print("📄 PDF Texte vide, conversion en image...")
                        img = pdf_helper.convert_pdf_to_image(content)
                        if img:
                            img_byte_arr = io.BytesIO()
                            img.save(img_byte_arr, format='JPEG')
                            raw_text = await ocr.extract_text_from_image_bytes(img_byte_arr.getvalue())
                else:
                    raw_text = await ocr.extract_text_from_image_bytes(content)

                if raw_text and len(raw_text) > 20:
                    rib_entry.raw_text = raw_text
                    db.add(rib_entry)
                    db.commit()
                    print(f"✅ Nouveau texte extrait ({len(raw_text)} chars).")
                else:
                    print("❌ Echec OCR: Toujours pas de texte trouvé.")
            except Exception as e:
                print(f"❌ Erreur lecture fichier: {e}")
        else:
            print("❌ Fichier physique introuvable.")

    # 3. Double Check before AI
    if not rib_entry.raw_text or len(rib_entry.raw_text) < 20:
        print("⛔ ABANDON: Pas de texte exploitable pour Gemini.")
        # Return row immediately
        banks_dict = crud.get_banks_as_dict(db)
        return templates.TemplateResponse("partials/rib_row.html", {
            "request": request, "rib": rib_entry, "banks_dict": banks_dict
        })

    # 4. CALL GEMINI
    print("🚀 Appel de Gemini en cours...")
    
    banks_list = crud.get_all_banks(db)
    banks_names = [b.name for b in banks_list]
    bank_codes = [b.code for b in banks_list]
    banks_dict = {b.code: {'name': b.name} for b in banks_list}

    try:
        parsed_data = await ocr.parse_extracted_text(
            rib_entry.raw_text, 
            doc_type="RIB", 
            known_banks_names=banks_names,
            known_bank_codes=bank_codes
        )
        print(f"🤖 Réponse Gemini: {parsed_data}")
    except Exception as e:
        print(f"💥 Crash Gemini: {e}")
        parsed_data = {"rib": None}

    # 5. Process & Save (SIMPLIFIED)
    status = "SUCCESS" if parsed_data.get("rib") else "ERROR"
    
    if parsed_data.get("rib"): # Only proceed if AI returned a RIB
        val_res = banking.validate_moroccan_rib(parsed_data["rib"], banks_dict, parsed_data["bankName"])
        
        if val_res["isValid"]:
            # Valid Length + Valid Bank Code (from DB)
            status = "SUCCESS"
            
            # Check Duplicates (exclude itself)
            current_dup = db.exec(
                crud.select(EmployeeRib).where(
                    EmployeeRib.period_id == rib_entry.period_id, 
                    EmployeeRib.rib == parsed_data["rib"],
                    EmployeeRib.id != rib_id
                )
            ).first()
            if current_dup:
                status = "DUPLICATE"
                print("⚠️ Status: DUPLICATE detected")
            
            # Check Source Consistency
            elif not ocr.validate_extraction_in_source(parsed_data["rib"], rib_entry.raw_text):
                status = "SUSPICIOUS"
                print("⚠️ Status: SUSPICIOUS (Source mismatch)")
        else:
            # Invalid Length OR Invalid Bank Code
            status = "ERROR"
    else:
        # AI did not return a RIB
        status = "ERROR"

    # Save
    rib_entry.rib = parsed_data.get("rib")
    rib_entry.first_name = parsed_data.get("firstName")
    rib_entry.last_name = parsed_data.get("lastName")
    rib_entry.ai_bank_name = parsed_data.get("bankName")
    rib_entry.status = status
    rib_entry.is_manually_corrected = False
    
    db.add(rib_entry)
    db.commit()
    db.refresh(rib_entry)

    print(f"✅ FIN DEBUG: Nouveau statut = {status}")
    print("---------------------------------------")

    return templates.TemplateResponse("partials/rib_row.html", {
        "request": request, 
        "rib": rib_entry,
        "banks_dict": banks_dict
    })

@router.post("/period/{period_id}/retry_all_errors")
async def retry_all_period_errors(
    request: Request,
    period_id: str,
    db: Session = Depends(get_session),
    user: dict = Depends(require_operator)
):
    period = crud.get_period_by_id(db, period_id)
    if not period or period.is_locked:
        raise HTTPException(status_code=400, detail="Action impossible")

    # Get banks context once
    banks_list = crud.get_all_banks(db)
    banks_names = [b.name for b in banks_list]
    bank_codes = [b.code for b in banks_list]
    banks_dict = {b.code: {'name': b.name} for b in banks_list}

    # Filter only problem ribs
    error_ribs = [r for r in period.ribs if r.status in ["ERROR", "SUSPICIOUS"]]

    for rib in error_ribs:
        if not rib.raw_text: continue
        
        # We reuse the logic (you could extract this to a service function to stay DRY)
        parsed = await ocr.parse_extracted_text(rib.raw_text, "RIB", banks_names, known_bank_codes=bank_codes)
        
        status = "SUCCESS" if parsed["rib"] else "ERROR"
        
        if parsed["rib"]: # Only proceed if AI returned a RIB
            val = banking.validate_moroccan_rib(parsed["rib"], banks_dict, parsed["bankName"])
            
            if val["isValid"]:
                status = "SUCCESS"
                if crud.check_duplicate_rib(db, period_id, parsed["rib"]):
                     status = "DUPLICATE"
                elif not ocr.validate_extraction_in_source(parsed["rib"], rib.raw_text):
                    status = "SUSPICIOUS"
            else:
                status = "ERROR"
        else:
            status = "ERROR"
        
        # Update
        rib.rib = parsed["rib"]
        rib.first_name = parsed["firstName"]
        rib.last_name = parsed["lastName"]
        rib.ai_bank_name = parsed["bankName"]
        rib.status = status
        rib.is_manually_corrected = False
        db.add(rib)

    db.commit()
    
    # Return the whole table to refresh UI
    # Recalculate stats
    db.refresh(period)
    stats = calculate_period_stats(period.ribs, banks_dict)
    
    return templates.TemplateResponse("partials/rib_table.html", {
        "request": request, 
        "period": period, 
        "stats": stats, 
        "user": user, 
        "banks_dict": banks_dict
    })

@router.delete("/rib/{rib_id}")
async def delete_rib(
    request: Request,
    rib_id: str, 
    db: Session = Depends(get_session),
    user: dict = Depends(require_operator)
):
    rib = db.get(crud.EmployeeRib, rib_id)
    if rib and rib.period.is_locked:
        raise HTTPException(status_code=400, detail="Period is locked. Cannot delete.")

    rib = crud.delete_rib_entry(db, rib_id)
    if rib:
        file_path = os.path.join(UPLOAD_DIR, rib.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)
    return Response(content="", status_code=200)

@router.delete("/period/{period_id}/all")
async def delete_all(
    request: Request, 
    period_id: str, 
    db: Session = Depends(get_session),
    user: dict = Depends(require_admin)
):
    period = crud.get_period_by_id(db, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Period not found")

    # Delete physical files
    for rib in period.ribs:
        file_path = os.path.join(UPLOAD_DIR, rib.file_name)
        if os.path.exists(file_path): os.remove(file_path)
    for cin in period.cins:
        file_path = os.path.join(UPLOAD_DIR, cin.file_name)
        if os.path.exists(file_path): os.remove(file_path)

    crud.delete_all_ribs_in_period(db, period_id)
    crud.delete_all_cins_in_period(db, period_id)
    
    period = crud.get_period_by_id(db, period_id)
    empty_stats = calculate_period_stats([], {}) # Empty dict
    
    return templates.TemplateResponse("partials/rib_table.html", {
        "request": request, "period": period, "stats": empty_stats, "user": user, "banks_dict": {}
    })

@router.delete("/period/{period_id}")
async def delete_period_route(
    request: Request,
    period_id: str,
    db: Session = Depends(get_session),
    user: dict = Depends(require_admin)
):
    period = db.get(crud.Period, period_id)
    if not period: return "Period not found"

    for rib in period.ribs:
        file_path = os.path.join(UPLOAD_DIR, rib.file_name)
        if os.path.exists(file_path): os.remove(file_path)
    for cin in period.cins:
        file_path = os.path.join(UPLOAD_DIR, cin.file_name)
        if os.path.exists(file_path): os.remove(file_path)

    crud.delete_period(db, period_id)
    return "OK"

@router.post("/periods/delete-all", response_class=HTMLResponse)
async def delete_all_periods_route(
    request: Request,
    db: Session = Depends(get_session),
    user: dict = Depends(require_admin)
):
    periods = crud.get_periods(db)
    for period in periods:
        for rib in period.ribs:
            file_path = os.path.join(UPLOAD_DIR, rib.file_name)
            if os.path.exists(file_path): os.remove(file_path)
        for cin in period.cins:
            file_path = os.path.join(UPLOAD_DIR, cin.file_name)
            if os.path.exists(file_path): os.remove(file_path)

    crud.delete_all_periods(db)
    periods = crud.get_periods(db)
    return templates.TemplateResponse("partials/period_list.html", {
        "request": request, "periods": periods, "user": user
    })

@router.get("/period/{period_id}/export")
async def export_period_excel(period_id: str, db: Session = Depends(get_session), user: dict = Depends(require_user)):
    period = crud.get_period_by_id(db, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Period not found")
    
    banks_dict = crud.get_banks_as_dict(db)
    
    data = []
    for rib in period.ribs:
        # Resolve bank name
        bank_name = ""
        if rib.rib:
            val = banking.validate_moroccan_rib(rib.rib, banks_dict, rib.ai_bank_name)
            bank_name = val["bankName"]

        data.append({
            "Statut": rib.status,
            "Nom": rib.last_name,
            "Prénom": rib.first_name,
            "RIB": rib.rib,
            "Banque": bank_name,
            "Fichier Source": rib.file_name,
            "Date d'ajout": rib.created_at.strftime("%d/%m/%Y %H:%M")
        })
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Données RIB")
        worksheet = writer.sheets['Données RIB']
        for column in worksheet.columns:
            max_length = 0
            column = [cell for cell in column]
            try:
                for cell in column:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                adjusted_width = (max_length + 2)
                worksheet.column_dimensions[column[0].column_letter].width = adjusted_width
            except:
                pass

    output.seek(0)
    safe_name = period.name.replace(" ", "_")
    headers = {"Content-Disposition": f'attachment; filename="Export_{safe_name}.xlsx"'}
    return StreamingResponse(
        output, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@router.get("/uploads/{filename}")
async def get_upload(filename: str, user: dict = Depends(require_user)):
    path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404)