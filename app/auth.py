from fastapi import Request, HTTPException, Depends
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from sqlmodel import Session
from app import crud
from app.database import get_session
from app.models import User

# THIS SHOULD BE IN AN ENVIRONMENT VARIABLE!
SECRET_KEY = "your-super-secret-key-that-is-long-and-random"
serializer = URLSafeTimedSerializer(SECRET_KEY)

def get_current_username(request: Request) -> str | None:
    token = request.cookies.get("session_token")
    if not token:
        return None

    try:
        return serializer.loads(token, max_age=3600 * 12)  # 12 hours
    except (SignatureExpired, BadTimeSignature):
        return None

async def get_current_user(
    request: Request,
    db: Session = Depends(get_session)
) -> User | None:
    username = get_current_username(request)
    if not username:
        return None
    
    user = crud.get_user_by_username(db, username=username)
    if user:
        return user

    return None

def require_user(request: Request, user: User = Depends(get_current_user)):
    if not user:
        if "hx-request" in request.headers:
            raise HTTPException(status_code=401, detail="Not authenticated")
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user

def require_admin(user: User = Depends(require_user)):
    if user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Access denied: Admins only")
    return user

def require_operator(user: User = Depends(require_user)):

    if user.role not in ["operator", "admin", "superadmin"]:

        raise HTTPException(status_code=403, detail="Access denied")

    return user



# --- NEW DEPENDENCY ---

def require_superadmin(user: User = Depends(require_user)):

    if user.role != "superadmin":

        raise HTTPException(status_code=403, detail="Access denied: Superadmin only")

    return user
