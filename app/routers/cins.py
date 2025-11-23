# app/routers/cins.py

import os
import io
import pandas as pd
from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, UploadFile, File, Form, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.database import get_session
from app import crud
from app.services import pdf_helper, ocr, cin_helper
from app.auth import require_user, require_operator, require_admin
from app.models import EmployeeCIN, Period

from app.services.validation_helper import validate_name

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- ROUTES ---

@router.post("/period/{period_id}/upload_cin")
async def upload_cin_files(
    request: Request,
    period_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_session),
    user: dict = Depends(require_operator) # Operator Only
):
    # 1. Check Period Status
    period = db.get(Period, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Period not found")
    if period.is_locked:
        raise HTTPException(status_code=400, detail="This period is locked.")

    results = []

    for file in files:
        try:
            # 2. Save File
            safe_name = f"CIN_{period_id}_{file.filename.replace(' ', '_')}"
            file_path = os.path.join(UPLOAD_DIR, safe_name)
            content = await file.read()
            
            with open(file_path, "wb") as f:
                f.write(content)
            
            # 3. Extract Text (OCR)
            raw_text = ""
            if file.content_type == "application/pdf":
                # Try text extraction first
                raw_text = pdf_helper.parse_pdf_text(content)
                # Fallback to Image OCR if text is empty (scanned PDF)
                if not raw_text or len(raw_text.strip()) < 50:
                    img = pdf_helper.convert_pdf_to_image(content)
                    if img:
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format='JPEG')
                        raw_text = await ocr.extract_text_from_image_bytes(img_byte_arr.getvalue())
            else:
                raw_text = await ocr.extract_text_from_image_bytes(content)

            # 4. AI Parsing (Gemini) with doc_type="CIN"
            parsed_data = await ocr.parse_extracted_text(raw_text, doc_type="CIN")
            
            # 5. Validate Logic (Expiry, Syntax)
            status = cin_helper.validate_cin(parsed_data)

            # 6. Create DB Entry
            cin_entry = EmployeeCIN(
                period_id=period_id,
                file_name=safe_name,
                cin_number=parsed_data.get("cin_number"),
                first_name=parsed_data.get("first_name"),
                last_name=parsed_data.get("last_name"),
                birth_date=parsed_data.get("birth_date"),
                validity_date=parsed_data.get("validity_date"),
                address=parsed_data.get("address"),
                raw_text=parsed_data.get("raw_text"),
                status=status
            )
            
            db.add(cin_entry)
            db.commit()
            db.refresh(cin_entry)
            results.append(cin_entry)
            
        except Exception as e:
            print(f"Error processing CIN {file.filename}: {e}")
            # Create error entry
            err_entry = EmployeeCIN(
                period_id=period_id,
                file_name=file.filename,
                raw_text=f"System Error: {str(e)}",
                status="ERROR"
            )
            db.add(err_entry)
            db.commit()
            results.append(err_entry)

    # Return the partial HTML for the new rows
    return templates.TemplateResponse("partials/cin_result.html", {
        "request": request, 
        "results": results
    })


@router.get("/cin/{cin_id}/modal", response_class=HTMLResponse)
async def get_cin_edit_modal(
    request: Request, 
    cin_id: str, 
    db: Session = Depends(get_session),
    user: dict = Depends(require_user)
):
    cin = db.get(EmployeeCIN, cin_id)
    if not cin:
        raise HTTPException(status_code=404, detail="CIN not found")
    
    return templates.TemplateResponse("partials/modal_cin_edit.html", {
        "request": request, 
        "cin": cin,
        "user": user
    })


@router.post("/cin/{cin_id}/update", response_class=HTMLResponse)
async def update_cin(
    request: Request, 
    cin_id: str, 
    cin_number: str = Form(...), 
    first_name: str = Form(...), 
    last_name: str = Form(...), 
    validity_date: str = Form(None),
    birth_date: str = Form(None),
    address: str = Form(None),
    db: Session = Depends(get_session),
    user: dict = Depends(require_operator)
):
    # 1. Get Entry
    cin = db.get(EmployeeCIN, cin_id)
    if not cin:
        raise HTTPException(status_code=404, detail="CIN not found")
    
    if cin.period.is_locked:
        raise HTTPException(status_code=400, detail="Period is locked")

    # 2. Update Fields
    cin.cin_number = cin_helper.clean_cin_number(cin_number)
    cin.first_name = first_name.upper()
    cin.last_name = last_name.upper()
    cin.validity_date = validity_date
    cin.birth_date = birth_date
    cin.address = address
    
    # 3. Re-Validate Logic
    # We construct a dict to pass to the helper
    validation_data = {
        "cin_number": cin.cin_number,
        "first_name": cin.first_name,
        "last_name": cin.last_name,
        "validity_date": cin.validity_date
    }
    
    new_status = cin_helper.validate_cin(validation_data)
    
    # Mark as manually corrected
    cin.status = new_status
    cin.is_manually_corrected = True
    
    db.add(cin)
    db.commit()
    db.refresh(cin)
    
    # 4. Return Updated Row
    return templates.TemplateResponse("partials/cin_row.html", {
        "request": request, 
        "cin": cin
    })


@router.delete("/cin/{cin_id}")
async def delete_cin(
    request: Request,
    cin_id: str, 
    db: Session = Depends(get_session),
    user: dict = Depends(require_operator)
):
    validate_name(first_name, "Prénom")
    validate_name(last_name, "Nom")
    cin = db.get(EmployeeCIN, cin_id)
    if not cin:
        return Response(content="", status_code=200) # Already gone
        
    if cin.period.is_locked:
        raise HTTPException(status_code=400, detail="Period is locked. Cannot delete.")

    # Delete File
    file_path = os.path.join(UPLOAD_DIR, cin.file_name)
    if os.path.exists(file_path):
        os.remove(file_path)
        
    # Delete DB Entry
    db.delete(cin)
    db.commit()
    
    return Response(content="", status_code=200)

# --- NEW EXPORT ROUTE ---

@router.get("/period/{period_id}/export_cin")
async def export_cin_excel(
    period_id: str, 
    db: Session = Depends(get_session), 
    user: dict = Depends(require_user)
):
    period = db.get(Period, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Period not found")
    
    data = []
    for cin in period.cins:
        data.append({
            "Statut": cin.status,
            "N° CIN": cin.cin_number,
            "Nom": cin.last_name,
            "Prénom": cin.first_name,
            "Date Naissance": cin.birth_date,
            "Date Validité": cin.validity_date,
            "Adresse": cin.address, # Included Address
            "Fichier Source": cin.file_name,
            "Date d'ajout": cin.created_at.strftime("%d/%m/%Y %H:%M")
        })
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    
    # Create Excel file in memory
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Données CIN")
        worksheet = writer.sheets['Données CIN']
        
        # Auto-adjust column width
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
        "Content-Disposition": f'attachment; filename="Export_CIN_{safe_name}.xlsx"'
    }
    return StreamingResponse(
        output, 
        headers=headers, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@router.delete("/period/{period_id}/cins/all")
async def delete_all_cins(
    request: Request,
    period_id: str,
    db: Session = Depends(get_session),
    user: dict = Depends(require_admin) # Only Admins can bulk delete
):
    period = db.get(Period, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Period not found")
    
    if period.is_locked:
        raise HTTPException(status_code=400, detail="Period is locked")

    # 1. Delete physical files for CINs
    for cin in period.cins:
        file_path = os.path.join(UPLOAD_DIR, cin.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)

    # 2. Delete DB entries
    crud.delete_all_cins_in_period(db, period_id)
    
    # 3. Refetch period to ensure empty list
    db.refresh(period)
    
    # 4. Return the updated table
    return templates.TemplateResponse("partials/cin_table.html", {
        "request": request, 
        "period": period
    })