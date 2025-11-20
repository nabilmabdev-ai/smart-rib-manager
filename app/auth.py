import uuid
import bcrypt
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse

# 1. Hardcoded Users
USERS = {
    "admin": {"password": "$2b$12$YlBuCG.NH63dfgHTCfA..Odxuq23itOhz2BveejWeqcytfzxEaXlq", "role": "admin"},
    "operator": {"password": "$2b$12$255v2cGPU8ANph/LQtoT1O2erF.9BFqWnMCIybJVZ0iCZRw3MaS..", "role": "operator"},
    "superadmin": {"password": "$2b$12$FbuH8qOM38RlEEsOzsGP0OBMWDPYM34TdIfQHy4RGTbSVX2Ral7vO", "role": "superadmin"}
}

# 2. In-Memory Session Store (resets when server restarts)
# Format: { "random-session-token": "username" }
SESSIONS = {}

def get_current_user(request: Request):
    """
    Check if the user has a valid session cookie.
    """
    token = request.cookies.get("session_token")
    
    if not token or token not in SESSIONS:
        # If API call (HTMX), return 401, else redirect to login
        if "hx-request" in request.headers:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return None # Signal to route that user is not logged in

    username = SESSIONS[token]
    return {"username": username, "role": USERS[username]["role"]}

# Dependency to PROTECT routes (Redirects to /login if not logged in)
def require_user(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user

# Dependency for Admin
def require_admin(request: Request):
    user = require_user(request)
    if user["role"] not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Access denied: Admins only")
    return user

# Dependency for Operator
def require_operator(request: Request):
    user = require_user(request)
    if user["role"] not in ["operator", "admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Access denied")
    return user