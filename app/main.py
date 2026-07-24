import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.routers import ai_categorize, categories, locations, map as map_router, reels
from app.seed import seed_if_empty
from app.web import templates

_ai_log_path = os.environ.get("AI_DEBUG_LOG_PATH", "data/ai_debug.log")
os.makedirs(os.path.dirname(_ai_log_path) or ".", exist_ok=True)
_ai_logger = logging.getLogger("app.ai")
_ai_logger.setLevel(logging.DEBUG)
if not _ai_logger.handlers:
    _ai_handler = logging.FileHandler(_ai_log_path)
    _ai_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _ai_logger.addHandler(_ai_handler)


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
app.include_router(categories.router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/health")
async def health():
    return {"status": "ok"}
