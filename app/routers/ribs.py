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

from app.services.validation_helper import validate_name

# Setup
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Register the function for Jinja
templates.env.globals['get_bank_name'] = banking.get_bank_name

def calculate_period_stats(ribs_list):
    """
    Calculates totals, valid extractions, errors, and bank distribution.
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
            
            # Add to Bank Distribution
            b_name = banking.get_bank_name(r.rib, r.ai_bank_name)
            if b_name:
                stats["bank_distribution"][b_name] = stats["bank_distribution"].get(b_name, 0) + 1
        
        elif r.status in ["ERROR", "SUSPICIOUS"]:
            stats["discrepancies"] += 1
            
    # Sort banks by count descending
    stats["bank_distribution"] = dict(
        sorted(stats["bank_distribution"].items(), key=lambda item: item[1], reverse=True)
    )
    
    return stats

UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

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
    
    stats = calculate_period_stats(period.ribs)
    return templates.TemplateResponse("period_detail.html", {
        "request": request, 
        "period": period,
        "stats": stats,
        "user": user
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
        
    stats = calculate_period_stats(period.ribs) 
    
    return templates.TemplateResponse("period_detail.html", {
        "request": request, 
        "period": period,
        "stats": stats,
        "user": user
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

            parsed_data = await ocr.parse_extracted_text(raw_text, doc_type="RIB")
            
            status = "SUCCESS" if parsed_data["rib"] else "ERROR"

            # 1. Check for duplicates
            if status == "SUCCESS" and crud.check_duplicate_rib(db, period_id, parsed_data["rib"]):
                status = "DUPLICATE"
            
            # 2. Validate against source text
            if status == "SUCCESS":
                is_valid_in_source = ocr.validate_extraction_in_source(
                    extracted_value=parsed_data["rib"], 
                    raw_text=raw_text
                )
                if not is_valid_in_source:
                    status = "SUSPICIOUS"

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
    stats = calculate_period_stats(period.ribs)
    
    return templates.TemplateResponse("partials/upload_result.html", {
        "request": request, 
        "results": results, 
        "stats": stats      
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
    validate_name(first_name, "Prénom")
    validate_name(last_name, "Nom")
    rib_entry = db.get(EmployeeRib, rib_id)
    if not rib_entry:
        raise HTTPException(status_code=404, detail="RIB not found")
        
    if rib_entry.period.is_locked:
        raise HTTPException(status_code=400, detail="Period is locked")

    clean_rib = banking.normalize_rib(rib)
    
    # --- MODIFICATION : Suppression de la validation algorithmique (Clé 97) ---
    # On garde simplement la validation de longueur (24 chiffres).
    
    new_status = "SUCCESS"
    
    # 1. Validation simple : 24 caractères numériques
    if len(clean_rib) != 24:
        new_status = "ERROR"
    
    # 2. Vérification des doublons (seulement si le RIB a changé)
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
        "rib": rib_entry
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

    # Delete physical files for RIBs
    for rib in period.ribs:
        file_path = os.path.join(UPLOAD_DIR, rib.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)
            
    # Delete physical files for CINs
    for cin in period.cins:
        file_path = os.path.join(UPLOAD_DIR, cin.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)

    crud.delete_all_ribs_in_period(db, period_id)
    crud.delete_all_cins_in_period(db, period_id)
    
    # Refetch period, which will now be empty
    period = crud.get_period_by_id(db, period_id)
    empty_stats = calculate_period_stats([]) 
    
    return templates.TemplateResponse("partials/rib_table.html", {
        "request": request, 
        "period": period,
        "stats": empty_stats,
        "user": user
    })

@router.delete("/period/{period_id}")
async def delete_period_route(
    request: Request,
    period_id: str,
    db: Session = Depends(get_session),
    user: dict = Depends(require_admin)
):
    # 1. Get all files associated with this period BEFORE deleting DB rows
    period = db.get(crud.Period, period_id)
    if not period:
        return "Period not found"

    # 2. Delete physical files for RIBs
    for rib in period.ribs:
        file_path = os.path.join(UPLOAD_DIR, rib.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)
            
    # 3. Delete physical files for CINs
    for cin in period.cins:
        file_path = os.path.join(UPLOAD_DIR, cin.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)

    # 4. Now delete from DB
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
        # Delete physical files for RIBs
        for rib in period.ribs:
            file_path = os.path.join(UPLOAD_DIR, rib.file_name)
            if os.path.exists(file_path):
                os.remove(file_path)
                
        # Delete physical files for CINs
        for cin in period.cins:
            file_path = os.path.join(UPLOAD_DIR, cin.file_name)
            if os.path.exists(file_path):
                os.remove(file_path)

    crud.delete_all_periods(db)
    
    # Refetch periods, which will be an empty list
    periods = crud.get_periods(db)
    return templates.TemplateResponse("partials/period_list.html", {
        "request": request, 
        "periods": periods, 
        "user": user
    })

@router.get("/period/{period_id}/export")
async def export_period_excel(period_id: str, db: Session = Depends(get_session), user: dict = Depends(require_user)):
    period = crud.get_period_by_id(db, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Period not found")
    
    data = []
    for rib in period.ribs:
        data.append({
            "Statut": rib.status,
            "Nom": rib.last_name,
            "Prénom": rib.first_name,
            "RIB": rib.rib,
            "Banque": banking.validate_moroccan_rib(rib.rib, rib.ai_bank_name)["bankName"] if rib.rib else "",
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
    headers = {
        "Content-Disposition": f'attachment; filename="Export_{safe_name}.xlsx"'
    }
    return StreamingResponse(
        output, 
        headers=headers, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@router.get("/uploads/{filename}")
async def get_upload(filename: str, user: dict = Depends(require_user)):
    path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404)