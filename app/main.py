# app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.database import create_db_and_tables, engine
from sqlmodel import Session
from app import crud
from app.routers import ribs, auth, cins, settings # Added settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        crud.create_initial_users(session)
        crud.create_initial_banks(session) # Seed banks
    yield

app = FastAPI(lifespan=lifespan, title="Smart RIB & CIN Manager")

@app.exception_handler(307)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(url=exc.headers["Location"])

os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(ribs.router)
app.include_router(cins.router)
app.include_router(settings.router) # Include new router

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)