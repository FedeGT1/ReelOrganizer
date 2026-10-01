# Design: Storico delle conversazioni nella chat "Chiedi all'AI"

## Obiettivo

La chat di ricerca sui reel (`/ask`, vedi `docs/superpowers/specs/2026-10-01-ai-ask-reels-design.md`) già persiste ogni conversazione in `AskSession`/`AskMessage`, ma oggi quelle righe si accumulano senza che l'utente possa mai rivederle: ogni apertura della pagina, cambio di filtro o click su "Nuova conversazione" parte da zero e la sessione precedente resta irraggiungibile. Questa funzionalità aggiunge un elenco delle conversazioni passate, consultabile dalla stessa pagina `/ask`, da cui l'utente può:

- riaprire una conversazione passata e continuare a scriverci (gli stessi filtri città/categoria con cui era stata fatta vengono ripristinati automaticamente);
- eliminare una conversazione che non serve più.

L'apertura della pagina `/ask` da zero continua a partire sempre da una conversazione vuota (comportamento invariato); lo storico è un'azione esplicita dell'utente, non un auto-resume.

## Collocazione nell'interfaccia

Niente pagina separata: l'elenco vive nella stessa pagina `/ask`, dentro un elemento HTML nativo `<details><summary>Conversazioni precedenti</summary>...</details>` -- un dropdown/accordion senza bisogno di JavaScript nuovo. Fa parte dello stesso pannello (`partials/ask_chat.html`) già ri-renderizzato per intero a ogni interazione (cambio filtro, nuovo messaggio, nuova conversazione); non è un fragment separato con proprio hx-target, per restare coerente con il pattern già in uso e non introdurre swap out-of-band per un elenco di questa scala.

Per chiarezza del codice, il markup della lista vive in un sotto-template incluso (`partials/ask_history_list.html`, via `{% include %}` di Jinja), ma la richiesta HTTP resta unica.

## Dati: bugfix `updated_at`

`AskSession.updated_at` è oggi impostato solo alla creazione e non viene mai aggiornato. Perché "più recente" nello storico abbia senso, `_run_ask_turn` deve aggiornarlo a ogni turno:

```python
ask_session.updated_at = datetime.utcnow()
session.add(ask_session)
session.commit()
```

(subito prima del `return ask_session` finale, dopo aver salvato il messaggio assistant).

## Etichette delle voci dello storico

Ogni voce mostra: **prima domanda (troncata) — ambito — data**, per esempio:

> Cosa mi consigli a Shibuya? — Tokyo / Kanto — Cibo — 01/10/2026 14:32

Tre nuove funzioni pure in `app/routers/ai_ask.py`:

```python
def _session_message_label(first_message: str, max_len: int = 60) -> str:
    text = (first_message or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


def _session_scope_label(location_name: Optional[str], category_label: Optional[str]) -> str:
    return f"{location_name or 'Tutte le città'} — {category_label or 'Tutte le categorie'}"


def _list_ask_sessions(session: Session) -> list[dict]:
    sessions = session.exec(select(AskSession).order_by(AskSession.updated_at.desc())).all()
    taxonomy = get_taxonomy(session)
    summaries = []
    for s in sessions:
        first_message = session.exec(
            select(AskMessage.content)
            .where(AskMessage.session_id == s.id, AskMessage.role == "user")
            .order_by(AskMessage.created_at)
        ).first()
        location = session.get(Location, s.location_id) if s.location_id else None
        category_label = (
            taxonomy[s.category_key]["label"] if s.category_key and s.category_key in taxonomy else None
        )
        summaries.append({
            "id": s.id,
            "message_label": _session_message_label(first_message or ""),
            "scope_label": _session_scope_label(location.name if location else None, category_label),
            "date_label": s.updated_at.strftime("%d/%m/%Y %H:%M"),
        })
    return summaries
```

`get_taxonomy` viene chiamato una sola volta fuori dal loop (non per ogni sessione). Ogni `AskSession` presente nello storico ha sempre almeno un messaggio `user` (viene creata solo dentro `_run_ask_turn`, insieme al primo messaggio), quindi `first_message` non è mai `None` nella pratica, ma il codice non assume nulla.

`_build_ask_chat_context` guadagna una chiave `"sessions": _list_ask_sessions(session)` nel dict restituito, così ogni risposta che renderizza `partials/ask_chat.html` porta sempre lo storico aggiornato.

## Riaprire una conversazione: `GET /ui/ask/panel`

L'endpoint guadagna un parametro opzionale `session_id`. Se presente, ha precedenza su `location_id`/`category_key` (stessa regola già usata da `_run_ask_turn` per i turni successivi al primo): si carica lo scope e la cronologia salvati su quella sessione, ignorando eventuali `location_id`/`category_key` nella query string.

```python
@ui_router.get("/panel")
def ui_ask_panel(
    request: Request,
    session_id: str = "",
    location_id: str = "",
    category_key: str = "",
    session: Session = Depends(get_session),
):
    if session_id:
        ask_session = session.get(AskSession, session_id)
        if ask_session is None:
            context = _build_ask_chat_context(
                session, None, None, None, notice="Conversazione non trovata, ricomincia pure da qui."
            )
            return templates.TemplateResponse(request, "partials/ask_chat.html", context)
        context = _build_ask_chat_context(
            session, ask_session.id, ask_session.location_id, ask_session.category_key
        )
        return templates.TemplateResponse(request, "partials/ask_chat.html", context)

    return templates.TemplateResponse(
        request,
        "partials/ask_chat.html",
        _build_ask_chat_context(session, None, location_id or None, category_key or None),
    )
```

Non viene fattorizzata una funzione condivisa con la logica simile dentro `_run_ask_turn`: lì un `session_id` inesistente deve propagarsi come `HTTPException(404)` (il chiamante POST ha già una gestione dedicata per quel caso), qui invece deve restituire direttamente un pannello con avviso. La duplicazione è minima (un `session.get` + un controllo di `None`) e tenerle separate è più chiaro che introdurre un'astrazione con due comportamenti di errore diversi.

## Eliminare una conversazione: `DELETE /ui/ask/history/{session_id}`

```python
@ui_router.delete("/history/{session_id}")
def ui_ask_delete_history(
    request: Request,
    session_id: str,
    current_session_id: str = Form(""),
    location_id: str = Form(""),
    category_key: str = Form(""),
    session: Session = Depends(get_session),
):
    ask_session = session.get(AskSession, session_id)
    if ask_session is not None:
        for m in session.exec(select(AskMessage).where(AskMessage.session_id == session_id)).all():
            session.delete(m)
        session.delete(ask_session)
        session.commit()

    reopen_session_id = None if current_session_id == session_id else (current_session_id or None)
    context = _build_ask_chat_context(session, reopen_session_id, location_id or None, category_key or None)
    return templates.TemplateResponse(request, "partials/ask_chat.html", context)
```

Se l'utente elimina la conversazione che ha aperta in quel momento, il pannello si azzera (torna vuoto, con i filtri correnti). Se elimina una voce diversa dalla conversazione aperta, quella resta intatta e si aggiorna solo l'elenco.

`current_session_id`/`location_id`/`category_key` arrivano dallo stesso contenitore `#ask-filters` già incluso ovunque nel pannello (vedi sotto) -- nessun nuovo meccanismo di hx-include.

## Template

`app/templates/partials/ask_chat.html`: aggiunto un nuovo hidden input dentro `#ask-filters`, che viaggia automaticamente con ogni richiesta che già usa `hx-include="#ask-filters"` (i due select, "Nuova conversazione", il form del messaggio, e ora anche i bottoni elimina dello storico):

```html
<input type="hidden" id="ask-current-session-id" name="current_session_id" value="{{ session_id }}">
```

e un `{% include "partials/ask_history_list.html" %}` subito dopo il blocco filtri.

`app/templates/partials/ask_history_list.html` (nuovo):

```html
<details class="ask-history">
    <summary>Conversazioni precedenti</summary>
    <ul class="ask-history-list">
        {% for s in sessions %}
        <li>
            <a href="#" class="ask-history-link" hx-get="/ui/ask/panel?session_id={{ s.id }}"
               hx-target="#ask-chat-panel" hx-swap="innerHTML">
                {{ s.message_label }} — {{ s.scope_label }} — {{ s.date_label }}
            </a>
            <button type="button" class="btn-delete" hx-delete="/ui/ask/history/{{ s.id }}"
                    hx-include="#ask-filters" hx-target="#ask-chat-panel" hx-swap="innerHTML"
                    aria-label="Elimina conversazione">🗑</button>
        </li>
        {% endfor %}
        {% if not sessions %}
        <li class="ask-history-empty">Nessuna conversazione salvata.</li>
        {% endif %}
    </ul>
</details>
```

Il bottone elimina è un elemento **fratello** del link, non annidato al suo interno (stesso schema già usato in `partials/reel_list.html` per le righe reel con bottone elimina) -- evita che un click sul cestino faccia scattare anche l'`hx-get` del link per bubbling dell'evento, senza bisogno di `stopPropagation()` in JS.

Nessun `hx-confirm` sul bottone elimina: nessun altro bottone elimina in questa app (reel, categorie, hub) usa una conferma, quindi si resta coerenti con la convenzione esistente piuttosto che introdurne una nuova solo qui.

## Gestione errori

- `session_id` nello storico che punta a una sessione già eliminata (es. due tab aperte, cancellata altrove): gestito dal ramo "non trovata" di `GET /ui/ask/panel` sopra -- stesso pattern già usato per `session_id` scaduti nei normali turni di chat.
- Eliminare una sessione già eliminata (doppio click, rete lenta): `DELETE` è naturalmente idempotente (`session.get` restituisce `None`, il blocco di cancellazione viene saltato, si prosegue comunque al render del pannello).

## Testing

- `tests/test_ai_ask.py`:
  - `_run_ask_turn` aggiorna `updated_at` della sessione a ogni turno (non resta fermo al valore di creazione);
  - `_list_ask_sessions` ordina per `updated_at` decrescente, etichetta correttamente scope "tutte le città/categorie" vs scope specifico, e trunca la prima domanda sopra 60 caratteri;
  - `GET /ui/ask/panel?session_id=X` ripristina cronologia e filtri di quella sessione, ignorando eventuali `location_id`/`category_key` passati in query string;
  - `GET /ui/ask/panel?session_id=inesistente` mostra l'avviso "Conversazione non trovata" invece di un 404 grezzo;
  - `DELETE /ui/ask/history/{id}` sulla conversazione correntemente aperta azzera il pannello;
  - `DELETE /ui/ask/history/{id}` su una conversazione diversa da quella aperta lascia intatta quella aperta e rimuove la voce dallo storico;
  - `DELETE /ui/ask/history/{id}` su un id già eliminato non solleva errori;
  - lo storico compare (con le sue etichette) nella risposta di `GET /ui/ask/panel` e di `POST /ui/ask/message`.

## Fuori scope

- Nessuna paginazione o ricerca testuale nello storico (scala personale, poche decine di conversazioni al più).
- Nessuna conferma prima di eliminare (coerente con il resto dell'app).
- Il caricamento iniziale di `/ask` resta sempre vuoto; nessun auto-resume dell'ultima conversazione.
