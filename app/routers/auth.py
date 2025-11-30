from fastapi import APIRouter, Request, Form, Depends, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from app import crud
from app.database import get_session
from app.auth import serializer, require_user, require_superadmin
from app.models import User
import bcrypt

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# --- LOGIN / LOGOUT ---

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    db: Session = Depends(get_session),
    username: str = Form(...),
    password: str = Form(...)
):
    user = crud.get_user_by_username(db, username=username)
    
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user.hashed_password.encode('utf-8')):
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": "Identifiants incorrects"
        }, status_code=400)

    session_token = serializer.dumps(username)
    
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session_token", 
        value=session_token, 
        httponly=True,
        max_age=3600 * 12
    )
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session_token")
    return response

# --- PROFILE (ALL USERS) ---

@router.get("/profile/modal", response_class=HTMLResponse)
async def get_profile_modal(
    request: Request, 
    user: User = Depends(require_user)
):
    return templates.TemplateResponse("partials/modal_profile.html", {
        "request": request, "user": user
    })

@router.post("/profile/password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_session),
    user: User = Depends(require_user)
):
    # Verify old password
    if not bcrypt.checkpw(old_password.encode('utf-8'), user.hashed_password.encode('utf-8')):
        return templates.TemplateResponse("partials/modal_profile.html", {
            "request": request, "user": user, "error": "Ancien mot de passe incorrect"
        })
    
    crud.update_password(db, user, new_password)
    
    return templates.TemplateResponse("partials/modal_profile.html", {
        "request": request, "user": user, "success": "Mot de passe modifié avec succès"
    })

# --- USER MANAGEMENT (SUPERADMIN ONLY) ---

@router.get("/admin/users/modal", response_class=HTMLResponse)
async def get_users_modal(
    request: Request,
    db: Session = Depends(get_session),
    user: User = Depends(require_superadmin)
):
    all_users = crud.get_all_users(db)
    return templates.TemplateResponse("partials/modal_users.html", {
        "request": request, "users": all_users, "current_user": user
    })

@router.post("/admin/users", response_class=HTMLResponse)
async def create_new_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_session),
    user: User = Depends(require_superadmin)
):
    if crud.get_user_by_username(db, username):
        all_users = crud.get_all_users(db)
        return templates.TemplateResponse("partials/modal_users.html", {
            "request": request, "users": all_users, "current_user": user, "error": "Cet identifiant existe déjà"
        })
    
    crud.create_user(db, username, password, role)
    
    # Return updated list
    all_users = crud.get_all_users(db)
    return templates.TemplateResponse("partials/modal_users.html", {
        "request": request, "users": all_users, "current_user": user, "success": "Utilisateur créé"
    })

@router.delete("/admin/users/{user_id}", response_class=HTMLResponse)
async def delete_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_superadmin)
):
    if user.id == user_id:
        raise HTTPException(status_code=400, detail="Impossible de se supprimer soi-même")

    crud.delete_user(db, user_id)
    
    all_users = crud.get_all_users(db)
    return templates.TemplateResponse("partials/modal_users.html", {
        "request": request, "users": all_users, "current_user": user
    })

@router.get("/guide", response_class=HTMLResponse)
async def help_guide(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("guide.html", {
        "request": request, 
        "user": user
    })