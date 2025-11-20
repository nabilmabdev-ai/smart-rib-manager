# app/routers/auth.py
from fastapi import APIRouter, Request, Form, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.auth import USERS, SESSIONS
import uuid
import bcrypt

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = USERS.get(username)
    
    # 1. Verify Credentials
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user["password"].encode('utf-8')):
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": "Identifiants incorrects"
        }, status_code=400)

    # 2. Create Session
    session_token = str(uuid.uuid4())
    SESSIONS[session_token] = username
    
    # 3. Set Cookie and Redirect
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session_token", 
        value=session_token, 
        httponly=True, # Security: JS cannot read this
        max_age=3600 * 12 # 12 Hours
    )
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session_token")
    return response
