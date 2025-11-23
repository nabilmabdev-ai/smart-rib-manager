# app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.database import create_db_and_tables, engine
from sqlmodel import Session
from app import crud
from app.routers import ribs, auth, cins

# This function runs before the app starts to ensure DB exists
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    # Create a single session to seed the DB
    with Session(engine) as session:
        crud.create_initial_users(session)
    yield

app = FastAPI(lifespan=lifespan, title="Smart RIB & CIN Manager")

# 1. Add Exception Handler for Redirects
# This catches the "307" error from require_user and does a real redirect
@app.exception_handler(307)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(url=exc.headers["Location"])

# 2. Mount Static Files
# This allows us to serve the uploaded images/PDFs at /uploads/filename
os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 3. Include Routers
app.include_router(auth.router)
app.include_router(ribs.router)
app.include_router(cins.router) # <--- Register the new CIN module

if __name__ == "__main__":
    import uvicorn
    # Running on port 8000
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)