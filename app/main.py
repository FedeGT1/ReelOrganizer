import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import require_env
from app.auth_middleware import AuthMiddleware
from app.db import create_db_and_tables, engine
from app.routers import ai_ask, ai_categorize, ai_multi_categorize, auth, categories, export, instagram_cookies, instagram_import, locations, map as map_router, reels
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

require_env("AUTH_USERNAME")
require_env("AUTH_PASSWORD")
_session_secret_key = require_env("SESSION_SECRET_KEY")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        seed_if_empty(session)
    yield


app = FastAPI(title="Japan Reel Organizer", lifespan=lifespan)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret_key,
    https_only=True,
    same_site="lax",
    max_age=60 * 60 * 24 * 30,
)
app.include_router(auth.router)
app.include_router(locations.router)
app.include_router(reels.router)
app.include_router(map_router.router)
app.include_router(map_router.ui_router)
app.include_router(reels.ui_router)
app.include_router(ai_categorize.router)
app.include_router(ai_categorize.ui_router)
app.include_router(ai_ask.ui_router)
app.include_router(ai_multi_categorize.router)
app.include_router(instagram_import.router)
app.include_router(categories.router)
app.include_router(categories.ui_router)
app.include_router(locations.ui_router)
app.include_router(instagram_cookies.ui_router)
app.include_router(export.router)
app.include_router(export.ui_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/categories")
async def categories_page(request: Request):
    return templates.TemplateResponse(request, "categories.html", {})


@app.get("/locations")
async def locations_page(request: Request):
    return templates.TemplateResponse(request, "locations.html", {})


@app.get("/export")
async def export_page(request: Request):
    return templates.TemplateResponse(request, "export.html", {})


@app.get("/instagram-cookies")
async def instagram_cookies_page(request: Request):
    return templates.TemplateResponse(request, "instagram_cookies.html", {})


@app.get("/ask")
async def ask_page(request: Request):
    return templates.TemplateResponse(request, "ask.html", {})


@app.get("/health")
async def health():
    return {"status": "ok"}
