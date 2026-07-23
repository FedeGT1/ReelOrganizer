from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.routers import ai_categorize, locations, map as map_router, reels
from app.seed import seed_if_empty
from app.web import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        seed_if_empty(session)
    yield


app = FastAPI(title="Japan Reel Organizer", lifespan=lifespan)
app.include_router(locations.router)
app.include_router(reels.router)
app.include_router(map_router.router)
app.include_router(map_router.ui_router)
app.include_router(reels.ui_router)
app.include_router(ai_categorize.router)
app.include_router(ai_categorize.ui_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/health")
async def health():
    return {"status": "ok"}
