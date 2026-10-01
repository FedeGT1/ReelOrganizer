# Design: AI Ask — chat di ricerca sui reel salvati

## Obiettivo

Aggiungere una nuova voce di menu ("Chiedi all'AI") che apre una chat testuale separata da quella esistente di categorizzazione. L'utente seleziona una città (o "tutte le città") e, opzionalmente, una categoria; il sistema recupera i reel salvati che corrispondono al filtro e li passa, insieme alla domanda dell'utente, al provider AI configurato (lo stesso usato per la categorizzazione: Anthropic Haiku o OpenAI "Luna" a seconda di `AI_PROVIDER`). La conversazione continua su più turni mantenendo lo storico.

Questa è una funzionalità di sola lettura/consultazione: non crea, modifica o elimina reel. È concettualmente distinta dalla chat di categorizzazione esistente (`app/routers/ai_categorize.py`, tabelle `AiSession`/`AiMessage`), che estrae un luogo strutturato da un singolo reel da salvare.

## Modello dati

Due nuove tabelle, indipendenti da quelle esistenti:

```python
class AskSession(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    location_id: Optional[str] = Field(default=None, foreign_key="location.id")
    category_key: Optional[str] = Field(default=None, foreign_key="category.key")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AskMessage(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    session_id: str = Field(foreign_key="asksession.id")
    role: str  # "user" | "assistant"
    content: str  # testo semplice, mai JSON
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

`location_id = None` significa "tutte le città"; `category_key = None` significa "tutte le categorie". A differenza di `AiMessage`, `AskMessage.content` è sempre testo semplice: non c'è un risultato strutturato da portare tra i turni, solo la risposta testuale del modello.

**Compatibilità con il DB esistente:** `create_db_and_tables()` chiama solo `SQLModel.metadata.create_all(engine)`, che crea esclusivamente le tabelle mancanti senza toccare quelle esistenti. Al prossimo deploy sulla VM, le due nuove tabelle vengono aggiunte senza alcun impatto sui dati già presenti (`Reel`, `Location`, `Category`, `ReelType`, `AiSession`, `AiMessage`).

## Recupero dei reel per il contesto

Riuso delle funzioni già esistenti in `app/routers/reels.py`:
- Filtro per città: stesso meccanismo di `_location_and_satellite_ids` (una città/hub include anche i suoi satelliti).
- Filtro per categoria: stesso meccanismo già usato in `list_reels`/`_reel_list_context` tramite `ReelType`.
- Se `location_id` è `None`, nessun filtro di città (tutti i reel, eventualmente ulteriormente filtrati per categoria).

Per ogni reel incluso nel contesto: nome del luogo (risolto da `Location`), etichette delle categorie (da `get_taxonomy`), `note`, `link`.

Per contenere il contesto quando il filtro è ampio ("tutte le città"), si applica un tetto fisso (`MAX_REELS_IN_CONTEXT = 150`, costante in `app/ai/prompts.py`): se i reel corrispondenti superano il tetto, si passano solo i primi 150 (ordinati per `created_at`) e il prompt di sistema segnala esplicitamente che l'elenco è parziale, così il modello non assume di avere la lista completa.

## Prompt e chiamata AI

Nuove funzioni in `app/ai/prompts.py`:

- `build_ask_response_schema() -> dict`: schema JSON minimo `{"answer": {"type": "string"}}`, `required: ["answer"]`, `additionalProperties: False`.
- `build_ask_system_prompt(reels: list[dict], location_name: Optional[str], category_label: Optional[str], truncated: bool) -> str`: descrive il ruolo dell'assistente, elenca i reel nel formato `luogo — categorie — nota (link)`, indica il filtro attivo (città/categoria o "nessun filtro"), segnala se la lista è troncata, e istruisce:
  - rispondere basandosi **prioritariamente** sui reel salvati forniti;
  - poter usare la ricerca web solo per completare informazioni assenti dai reel salvati (es. orari, novità), dando a quei risultati un peso inferiore rispetto ai dati salvati e segnalando chiaramente quando un'informazione proviene dal web e non dai reel dell'utente;
  - se non ci sono reel che corrispondono al filtro, dirlo esplicitamente invece di inventare contenuti.

Nuova funzione in `app/ai/client.py`:

```python
def ask(
    reels: list[dict], location_name: Optional[str], category_label: Optional[str],
    truncated: bool, messages: list[dict[str, str]]
) -> dict[str, Any]:
    system = build_ask_system_prompt(reels, location_name, category_label, truncated)
    schema = build_ask_response_schema()
    return get_provider().call_json(system, messages, schema, enable_web_search=True)
```

Riusa `AIProvider.call_json` esistente (nessuna modifica al protocollo né ai provider): la risposta è sempre `{"answer": "..."}` indipendentemente dal provider attivo.

## Routing

Nuovo file `app/routers/ai_ask.py`, seguendo lo stile di `ai_categorize.py`:

- `ui_router = APIRouter(prefix="/ui/ask", tags=["ask-ui"])`
- `GET /ui/ask/panel?location_id=&category_key=`: renderizza il pannello completo (select città, select categoria, storico vuoto) per lo scope indicato. Usato al caricamento pagina, al cambio di un select, e dal bottone "Nuova conversazione".
- `POST /ui/ask/message` (form: `session_id`, `location_id`, `category_key`, `message`):
  - se `session_id` è vuoto: crea un nuovo `AskSession` con lo scope ricevuto;
  - salva il messaggio utente come `AskMessage`;
  - ricarica i reel per lo scope della sessione (sempre dal DB, non dalla history, così riflette eventuali modifiche fatte nel frattempo);
  - costruisce la history dei messaggi per la chiamata AI (tutti gli `AskMessage` della sessione, in ordine);
  - chiama `ai_client.ask(...)`; in caso di `(AIProviderError, RuntimeError)` usa una risposta di fallback testuale ("Errore nel contattare l'assistente, riprova.");
  - salva la risposta come `AskMessage` (role `assistant`, content = testo di `answer`);
  - rirenderizza il pannello chat.
- Pagina `GET /ask` in `app/main.py`, nello stesso stile di `categories_page`/`locations_page`: `return templates.TemplateResponse(request, "ask.html", {})`.

## Template e UI

- `app/templates/ask.html`: estende `base.html`, pagina intera come `locations.html`/`categories.html`. Contiene le due `<select>` (città — opzioni: "Tutte le città" + elenco hub; categoria — opzioni: "Tutte le categorie" + taxonomy) con `hx-get="/ui/ask/panel"` su `change`, target il pannello chat; e il bottone "Nuova conversazione" che rifà la stessa GET con i valori correnti dei select.
- `app/templates/partials/ask_chat.html`: bolle di chat per lo storico (`role == 'user'` / `'assistant'`). Form di invio messaggio con campi hidden `session_id`, `location_id`, `category_key`.
- **Revisione post-implementazione (2026-10-01):** la decisione iniziale "niente rendering markdown" è stata invertita su richiesta esplicita dell'utente, che preferisce vedere grassetto e link cliccabili nelle risposte. Il turno `user` resta testo semplice (auto-escaped da Jinja, nessun rendering); il turno `assistant` passa invece dal filtro Jinja `answer_markdown` (`app/ai/answer_markdown.py`), che: 1) converte il markdown in HTML con la libreria `markdown`; 2) sanifica l'HTML con `nh3` (tag consentiti: `p, strong, em, a, ul, ol, li, code, pre, blockquote, br, h3-h6, hr`; solo `href` su `a`; solo schema `http`/`https`; `target="_blank"` e `rel="noopener noreferrer"` forzati sui link). Il prompt in `build_ask_system_prompt` ora incoraggia esplicitamente **grassetto** e link in stile markdown per le citazioni, invece di proibirli.
- `app/templates/base.html`: nuova voce `<a href="/ask">Chiedi all'AI</a>` nel `<nav>`.

Cambiare uno dei due select azzera la conversazione corrente (nuova `GET /ui/ask/panel` con `session_id` implicitamente vuoto), perché il contesto reel passato all'AI cambierebbe a metà conversazione.

## Gestione errori

- Stessa convenzione di `ai_categorize.py`: `(AIProviderError, RuntimeError)` catturati attorno alla chiamata AI, con messaggio assistente di fallback invece di un 500.
- Nessun reel nello scope selezionato: la conversazione parte comunque; il prompt di sistema indica esplicitamente l'assenza di dati per quel filtro.
- `session_id` riferito a una sessione non più esistente (caso raro, nessuna UI per cancellarle manualmente oggi): stesso pattern di `ai_categorize.py` — 404 intercettato lato router, pannello ricaricato da zero con un avviso.

## Testing

- `tests/test_ai_prompts.py`: nuovi test per `build_ask_system_prompt` (contenuto reel, filtro città/categoria, caso troncato, caso nessun reel) e `build_ask_response_schema`.
- Nuovo `tests/test_ai_ask.py`, sul modello di `test_ai_categorize.py`:
  - caricamento pannello iniziale;
  - primo messaggio crea `AskSession` con lo scope corretto e filtra i reel per città/categoria come atteso;
  - messaggio successivo riusa la sessione esistente e mantiene lo storico;
  - scope "tutte le città"/"tutte le categorie" (nessun filtro);
  - scope senza reel corrispondenti;
  - fallback su errore provider.

## Fuori scope

- Nessuna possibilità di creare/modificare reel da questa chat (è read-only).
- Nessuna cancellazione/gestione manuale delle sessioni `AskSession` esistenti (si accumulano nel DB come già fa `AiSession`; non diverso dal comportamento attuale).
- Rendering markdown del turno `user` (solo il turno `assistant` viene renderizzato; vedi revisione post-implementazione sopra).
