from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.seed import seed_if_empty


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        seed_if_empty(session)
    yield


app = FastAPI(title="Japan Reel Organizer", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
