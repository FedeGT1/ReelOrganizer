# Design — User-customizable categories

Status: approved by user, ready for implementation planning.

## 1. Goal

Replace the fixed, hardcoded taxonomy (`food`, `culture`, `nature`, `shopping`,
`stay`, `transport`, `experience` — currently a Python constant in
`app/taxonomy.py`) with a user-editable set of categories stored in the
database. The user can add, rename/re-icon/re-color, and delete categories
from a dedicated management page. Every existing consumer of the fixed
taxonomy — the manual reel form, the map filter chips, the reel-list type
filter, and the AI categorization schema/prompt — must read the current set
of categories at request time instead of importing a static constant, so a
change made in the management page is reflected everywhere immediately.

## 2. Data model

New table in `app/models.py`, alongside the existing `Location`/`Reel`/etc.:

```python
class Category(SQLModel, table=True):
    key: str = Field(primary_key=True)
    label: str
    icon: str
    color: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- `key` is a URL-safe slug generated **once**, from `label`, at creation time
  (see §4) — it is the stable identifier stored in `ReelType.type` and never
  changes afterward, even if the user later edits `label`. This means
  renaming a category never orphans or requires rewriting existing reels'
  type tags.
- `ReelType.type` (`app/models.py`) is unchanged in shape (still a plain
  `str` primary-key column) but now declares `foreign_key="category.key"`,
  matching how `Reel.location_id` already declares `foreign_key="location.id"`.
- Ordering in every listing (management page, filter chips, checkboxes) is
  by `created_at` — no separate manual-ordering feature (§7).

### Seed data

`app/seed.py` gains an independent seeding guard for categories (separate
from the existing hub/satellite guard, so clearing one doesn't require
re-seeding the other):

```python
if session.exec(select(Category)).first() is None:
    for key, label, icon, color in DEFAULT_CATEGORIES:
        session.add(Category(key=key, label=label, icon=icon, color=color))
    session.commit()
```

`DEFAULT_CATEGORIES` reuses the exact same 7 `(key, label, icon, color)`
tuples that `app/taxonomy.py` has today, so a reel already tagged
`food`/`culture`/etc. keeps displaying correctly after this change (the DB
resets fresh per the project's existing "no migrations, delete `data/*.db`"
policy — see README — so this only matters for a freshly recreated DB, but
keeping the same keys/values is what makes that recreation unsurprising).

## 3. `app/taxonomy.py` is deleted; replaced by `app/routers/categories.py` helpers

The fixed `TAXONOMY` dict and `VALID_TYPES` set are removed entirely.
Everything that previously did `from app.taxonomy import TAXONOMY,
VALID_TYPES` switches to calling two functions, defined in the new
`app/routers/categories.py` (the router that also owns category CRUD — see
§5) and imported cross-router the same way `app/routers/ai_categorize.py`
already imports `_is_safe_link`/`_reel_list_context` from
`app/routers/reels.py`:

```python
def get_taxonomy(session: Session) -> dict[str, dict]:
    """Drop-in replacement for the old TAXONOMY constant, shape-compatible
    with every template that does taxonomy[key].icon / .label / .color."""
    categories = session.exec(select(Category).order_by(Category.created_at)).all()
    return {c.key: {"label": c.label, "icon": c.icon, "color": c.color} for c in categories}


def get_valid_type_keys(session: Session) -> set[str]:
    """Drop-in replacement for the old VALID_TYPES constant."""
    return set(session.exec(select(Category.key)).all())
```

Because `get_taxonomy()` returns the exact same `{key: {"label", "icon",
"color"}}` shape the templates already consume, **no template changes are
needed** in `partials/reel_list.html`, `partials/map.html`, or
`partials/ai_chat.html` — only the Python call sites that build their
context dicts change, from a module-level constant to a per-request DB call.

### Call sites that change

| File | Today | Becomes |
|---|---|---|
| `app/routers/reels.py` | `from app.taxonomy import TAXONOMY, VALID_TYPES` | `from app.routers.categories import get_taxonomy, get_valid_type_keys`; call both with `session` inside `_reel_list_context`, `create_reel`, `ui_create_reel` |
| `app/routers/map.py` | `from app.taxonomy import TAXONOMY` | `get_taxonomy(session)` inside `ui_map` |
| `app/routers/ai_categorize.py` | `from app.taxonomy import TAXONOMY, VALID_TYPES` | `get_taxonomy(session)` in `_build_ai_chat_context`; `get_valid_type_keys(session)` in `_run_turn` and `ui_ai_confirm` |
| `app/ai/prompts.py` | `from app.taxonomy import TAXONOMY, VALID_TYPES` (module-level, used to build a static `RESPONSE_SCHEMA` constant and describe types in the prompt) | Both become **parameters**, not imports — see §6 |

## 4. Slug generation

```python
import re
import unicodedata

def slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
```

Handles accented Italian labels (`"Città notturna"` → `"citta-notturna"`).
If the result is empty (label has no letters/digits at all), category
creation fails with `400`. If the computed slug already exists as another
category's `key`, creation fails with `409` — the user picks a different
name; no auto-suffixing.

## 5. Routes (`app/routers/categories.py`, new)

Mirrors the existing per-resource pattern in this app (`locations.py`,
`reels.py`): a JSON API under `/api/categories` plus HTMX routes under
`/ui/categories`.

### JSON API

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/categories` | List all categories, ordered by `created_at`. |
| POST | `/api/categories` | Body `{label, icon, color}`. Computes `key` via `slugify(label)`; `400` if empty, `409` if the key already exists. Returns the created `Category`. |
| PUT | `/api/categories/{key}` | Body `{label, icon, color}`. Updates those three fields; `key` itself is never editable through this endpoint. `404` if the key doesn't exist. |
| DELETE | `/api/categories/{key}` | Deletes the category. First deletes every `ReelType` row with `type == key` (per the user's decision: reels keep existing, they just lose that one tag — a reel can have several). `404` if the key doesn't exist. |

### HTMX UI

| Method | Path | Behavior |
|---|---|---|
| GET | `/ui/categories` | Renders `partials/category_list.html`: the full list (icon, label, color swatch, "Modifica"/"Elimina" per row) followed by the "Aggiungi categoria" form. |
| POST | `/ui/categories` | Form fields `label`, `icon`, `color` → create, then re-render the list partial. Same `400`/`409` rules as the JSON API. |
| GET | `/ui/categories/{key}/edit` | Renders `partials/category_edit_row.html` — that one row becomes an inline form (label/icon/color prefilled, Salva/Annulla), swapped in place of the static row. |
| POST | `/ui/categories/{key}` | Form fields `label`, `icon`, `color` → update, then re-render the full list partial (returns the row to its static display state). |
| DELETE | `/ui/categories/{key}` | Delete (cascading `ReelType` removal as above), then re-render the full list partial. |

## 5.5 Page and navigation

`app/main.py` registers the new router (`categories.router`,
`categories.ui_router`) and a new page route:

```python
@app.get("/categories")
async def categories_page(request: Request):
    return templates.TemplateResponse(request, "categories.html", {})
```

`app/templates/categories.html` (new, sibling to `index.html`, extends
`base.html`):

```html
{% extends "base.html" %}
{% block content %}
<section id="category-list" hx-get="/ui/categories" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento categorie...</p>
</section>
{% endblock %}
```

`app/templates/base.html` gains a small header nav (today it's just an
`<h1>` with no links at all) so the two pages can reach each other:

```html
<header>
    <h1>Japan Reel Organizer</h1>
    <nav>
        <a href="/">Home</a>
        <a href="/categories">Gestisci categorie</a>
    </nav>
</header>
```

## 6. AI schema/prompt: from constants to parameters

`app/ai/prompts.py` currently exports a static `RESPONSE_SCHEMA` dict and a
`build_system_prompt(hub_names)` function that both import the fixed
`TAXONOMY`/`VALID_TYPES`. Since categories can now change between requests,
neither can stay a module-level constant built from a static import — both
become functions parameterized on the *current* categories, exactly the way
`hub_names` is already recomputed fresh on every turn in `_run_turn`:

```python
def build_response_schema(valid_type_keys: Iterable[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "place_name": {"type": "string"},
            "near_hub": {"type": ["string", "null"]},
            "types": {"type": "array", "items": {"type": "string", "enum": sorted(valid_type_keys)}},
            "note": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "question": {"type": ["string", "null"]},
            "lat": {"type": ["number", "null"]},
            "lon": {"type": ["number", "null"]},
        },
        "required": ["place_name", "near_hub", "types", "note", "confidence", "question", "lat", "lon"],
        "additionalProperties": False,
    }


def build_system_prompt(hub_names: Iterable[str], categories: dict[str, str]) -> str:
    # categories: key -> label (e.g. {"food": "Cibo", ...})
    types_list = ", ".join(f"{key} ({label})" for key, label in categories.items())
    ...  # same body as today, but built from `categories` instead of TAXONOMY
```

`app/ai/client.py`'s `categorize()` gains a parameter to carry this through:

```python
def categorize(hub_names: list[str], categories: dict[str, str], messages: list[dict[str, str]]) -> dict[str, Any]:
    schema = build_response_schema(categories.keys())
    system = build_system_prompt(hub_names, categories)
    ...  # same client.messages.create(...) call, using `schema` instead of the old RESPONSE_SCHEMA constant
```

`_run_turn` (`app/routers/ai_categorize.py`) fetches `categories =
get_taxonomy(session)`, reduces it to `{key: info["label"] for key, info in
categories.items()}`, and passes that into `ai_client.categorize(hub_names,
category_labels, api_messages)`. The post-call filter
(`result["types"] = [t for t in result.get("types", []) if t in
VALID_TYPES]`) becomes `if t in get_valid_type_keys(session)`.

### Ripple: every caller of `ai_client.categorize` in tests breaks

This is the single largest mechanical side effect of this change.
`ai_client.categorize` currently has the signature `(hub_names, messages)`;
every test that does `monkeypatch.setattr(ai_client, "categorize", lambda
hub_names, messages: {...})` (or a `def fake_categorize(hub_names,
messages):`) across `tests/test_ai_client.py`, `tests/test_ai_categorize.py`,
and `tests/test_ai_ui.py` must add the new middle parameter. There are
roughly 15-20 such call sites across those three files — the implementation
plan must update every one, not just add new tests.

### Ripple: tests asserting on type-filtering need a seeded `Category` row

Today, tests that exercise the `VALID_TYPES` filter (e.g. asserting that a
model-returned `"food"` type survives while `"not-a-real-type"` is dropped)
rely on `VALID_TYPES` being a hardcoded constant — always present, no setup
needed. Once filtering depends on `get_valid_type_keys(session)`, those same
tests run against the **test** `session` fixture's fresh, unseeded in-memory
SQLite DB (the app's `seed_if_empty` only runs via the real lifespan, never
via the `session`/`client` test fixtures — confirmed in `tests/conftest.py`).
Any test asserting a specific type key survives filtering must now add a
matching `session.add(Category(key="food", label="Cibo", icon="🍜",
color="#A63A2E"))` (or whichever key it needs) before exercising the code
under test — otherwise `get_valid_type_keys` returns an empty set and every
type gets filtered out, breaking the assertion for a reason unrelated to
what the test is meant to check. The plan must audit every test currently
relying on a specific taxonomy key surviving filtering (`tests/test_ai_categorize.py`,
`tests/test_ai_ui.py`, `tests/test_reels_api.py`, `tests/test_ui_fragments.py`,
`tests/test_map_api.py`) and add the needed seed rows.

## 7. Out of scope

- Manual reordering (drag-and-drop) of categories — creation order
  (`created_at`) is the only ordering.
- An icon picker or curated color palette — plain text/native color input
  only (user's decision).
- Any protection against deleting the last remaining category — if the user
  deletes all of them, the manual form's checkbox list and the AI's `types`
  enum are simply empty; not guarded against, matching this app's existing
  "trust the single user" posture (e.g. lat/lon range isn't validated
  either).
- Multi-user conflict handling on category edits — single-user personal app,
  same as the rest of this codebase.
- Migrating away from the project's existing "no DB migrations, delete
  `data/*.db` to pick up schema changes" policy — this feature follows that
  same policy for the new `Category` table and the `ReelType.type` foreign
  key addition.

## 8. Testing

- New `tests/test_categories_api.py`: list/create/update/delete via
  `/api/categories`; slug generation (including accented-character
  normalization); `409` on duplicate slug; `400` on an unslugifiable label;
  `404` on updating/deleting an unknown key; deleting a category removes
  only the matching `ReelType` rows and leaves the `Reel` itself and any
  other type tags intact.
- New `tests/test_categories_ui.py`: `GET /ui/categories` renders the list +
  add form; `POST /ui/categories` creates and re-renders; `GET
  /ui/categories/{key}/edit` renders the inline edit row; `POST
  /ui/categories/{key}` updates and re-renders; `DELETE
  /ui/categories/{key}` removes it and re-renders, with the same cascading
  `ReelType` behavior as the JSON API.
- `tests/test_taxonomy.py` is deleted (the module it tests no longer
  exists); its "seed produces exactly these 7 categories with these
  labels/icons/colors" coverage moves to a seed test in
  `tests/test_seed.py`.
- `tests/test_ai_client.py`, `tests/test_ai_prompts.py`,
  `tests/test_ai_categorize.py`, `tests/test_ai_ui.py`: updated per the two
  ripple sections in §6 above (signature change + seeded `Category` rows).
- `tests/test_reels_api.py`, `tests/test_ui_fragments.py`,
  `tests/test_map_api.py`: any test relying on a specific type key
  surviving filtering gets a matching `Category` row added to its `session`
  setup.
