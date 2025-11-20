# app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.database import create_db_and_tables
from app.routers import ribs, auth

# This function runs before the app starts to ensure DB exists
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan, title="RIB Manager Python")

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
app.include_router(auth.router) # <--- Add this
app.include_router(ribs.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)