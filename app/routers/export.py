import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel, ReelType
from app.routers.categories import get_taxonomy
from app.web import templates

router = APIRouter(prefix="/api/export", tags=["export"])
ui_router = APIRouter(prefix="/ui", tags=["export-ui"])


def _slugify_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _hub_locations(session: Session, hub: Location) -> list[Location]:
    satellites = session.exec(select(Location).where(Location.parent_id == hub.id)).all()
    return sorted([hub, *satellites], key=lambda loc: loc.name)


def _reel_line(note: Optional[str], category_labels: list[str]) -> Optional[str]:
    categories_part = f"**{', '.join(category_labels)}**" if category_labels else None
    if categories_part and note:
        return f"- {categories_part} — {note}"
    if categories_part:
        return f"- {categories_part}"
    if note:
        return f"- {note}"
    return None


def build_export_markdown(session: Session, hub_id: Optional[str] = None) -> str:
    taxonomy = get_taxonomy(session)

    hub_query = select(Location).where(Location.is_hub == True)
    if hub_id is not None:
        hub_query = hub_query.where(Location.id == hub_id)
    hubs = sorted(session.exec(hub_query).all(), key=lambda loc: loc.name)

    sections = []
    for hub in hubs:
        location_blocks = []
        for location in _hub_locations(session, hub):
            reels = session.exec(select(Reel).where(Reel.location_id == location.id)).all()
            lines = []
            for reel in reels:
                types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
                labels = [taxonomy[t.type]["label"] for t in types if t.type in taxonomy]
                line = _reel_line(reel.note, labels)
                if line:
                    lines.append(line)
            if lines:
                location_blocks.append(f"### {location.name}\n" + "\n".join(lines))
        if location_blocks:
            sections.append(f"## {hub.name}\n\n" + "\n\n".join(location_blocks))

    return "\n\n".join(sections)


@router.get("/markdown")
def export_markdown(hub_id: Optional[str] = None, session: Session = Depends(get_session)):
    hub = None
    if hub_id is not None:
        hub = session.get(Location, hub_id)
        if hub is None or not hub.is_hub:
            raise HTTPException(status_code=404, detail="Hub not found")

    content = build_export_markdown(session, hub_id)
    filename = f"export-{_slugify_filename(hub.name)}.md" if hub else "export.md"

    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@ui_router.get("/export")
def ui_export_panel(request: Request, session: Session = Depends(get_session)):
    hubs = sorted(
        session.exec(select(Location).where(Location.is_hub == True)).all(),
        key=lambda loc: loc.name,
    )
    return templates.TemplateResponse(request, "partials/export_panel.html", {"hubs": hubs})
