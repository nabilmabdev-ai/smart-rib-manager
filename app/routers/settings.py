# app/routers/settings.py
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from app.database import get_session
from app import crud
from app.auth import require_admin
from app.models import User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/admin/banks/modal", response_class=HTMLResponse)
async def get_banks_modal(
    request: Request,
    db: Session = Depends(get_session),
    user: User = Depends(require_admin)
):
    banks = crud.get_all_banks(db)
    return templates.TemplateResponse("partials/modal_banks.html", {
        "request": request, "banks": banks
    })

@router.post("/admin/banks", response_class=HTMLResponse)
async def add_bank(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_session),
    user: User = Depends(require_admin)
):
    if len(code) != 3 or not code.isdigit():
        banks = crud.get_all_banks(db)
        return templates.TemplateResponse("partials/modal_banks.html", {
            "request": request, "banks": banks, "error": "Le code doit faire 3 chiffres"
        })
        
    # Check if exists
    existing = db.get(crud.Bank, code)
    if existing:
        banks = crud.get_all_banks(db)
        return templates.TemplateResponse("partials/modal_banks.html", {
            "request": request, "banks": banks, "error": "Ce code existe déjà"
        })
        
    crud.create_bank(db, code, name)
    
    banks = crud.get_all_banks(db)
    return templates.TemplateResponse("partials/modal_banks.html", {
        "request": request, "banks": banks, "success": "Banque ajoutée"
    })

@router.delete("/admin/banks/{code}", response_class=HTMLResponse)
async def delete_bank(
    request: Request,
    code: str,
    db: Session = Depends(get_session),
    user: User = Depends(require_admin)
):
    crud.delete_bank(db, code)
    banks = crud.get_all_banks(db)
    return templates.TemplateResponse("partials/modal_banks.html", {
        "request": request, "banks": banks
    })