# Specifiche — Japan Reel Organizer (versione Python)

## 1. Obiettivo

Riscrivere in Python il prototipo web (attualmente un singolo file HTML/JS con storage in-browser) che organizza i reel Instagram salvati per un viaggio in Giappone. L'app permette di:

1. Categorizzare i reel per **luogo** (città/regione principale → gita di un giorno vicina) e per **tipo di contenuto** (food, cultura, natura, shopping, alloggio, trasporti, esperienza).
2. Visualizzarli su una **mappa schematica stile linea ferroviaria**: stazioni grandi = città/regioni principali, stazioni piccole collegate = gite di un giorno.
3. Categorizzare un reel **assistiti da un AI generativo**: l'utente incolla link + didascalia (o una descrizione libera), l'AI propone luogo e tag; se non ha abbastanza informazioni fa una domanda di chiarimento prima di proporre.

Questo documento descrive cosa costruire, non è codice. È pensato per essere dato in pasto a Claude Code come brief di partenza.

## 2. Stack proposto (default, modificabile)

- **Backend**: Python 3.11+, **FastAPI**
- **Persistenza**: **SQLite** via **SQLModel** (o SQLAlchemy puro se preferisci) — file locale, niente server DB esterno
- **Frontend**: server-rendered con **Jinja2**, interattività leggera con **HTMX** + un po' di JS vanilla per il disegno SVG della mappa (nessun framework JS pesante necessario)
- **AI**: **Anthropic Python SDK** (`anthropic`), modello `claude-sonnet-4-6` (o quello disponibile al momento), chiamata `messages.create` con `system` + `messages`
- **Esecuzione**: `uvicorn` in locale, single-user, nessuna autenticazione richiesta (è un'app personale)

> Se preferisci Flask/Django, o un frontend diverso (es. Streamlit per prototipare più in fretta, o una SPA separata), la logica di dominio nella sezione 4 resta valida: cambia solo il layer di presentazione.

## 3. Struttura progetto suggerita

```
japan-reel-organizer/
├── app/
│   ├── main.py              # entrypoint FastAPI
│   ├── models.py            # modelli SQLModel: Location, Reel
│   ├── db.py                # engine + sessione SQLite
│   ├── seed.py               # dati di default (hub + gite predefinite)
│   ├── routers/
│   │   ├── locations.py     # CRUD tappe
│   │   ├── reels.py         # CRUD reel + filtri
│   │   └── ai_categorize.py # endpoint chat AI
│   ├── ai/
│   │   ├── client.py        # wrapper attorno all'SDK Anthropic
│   │   └── prompts.py       # system prompt, schema JSON atteso
│   ├── templates/           # Jinja2: index.html, partials/*
│   └── static/               # css, eventuale js per la mappa
├── data/
│   └── japan_reels.db       # file SQLite (gitignore)
├── requirements.txt
└── README.md
```

## 4. Modello dati

### Location
| campo       | tipo                | note |
|-------------|---------------------|------|
| id          | str (uuid o slug)   | chiave primaria |
| name        | str                 | es. "Kyoto - Osaka / Kansai" |
| is_hub      | bool                | True = stazione principale, False = gita/satellite |
| parent_id   | str, nullable       | valorizzato solo se `is_hub=False`; punta a una Location con `is_hub=True` |
| x, y        | float, nullable     | coordinate sulla mappa SVG (solo per gli hub; le posizioni dei satelliti si calcolano a runtime in modo radiale attorno al genitore, come nel prototipo) |

### Reel
| campo        | tipo            | note |
|--------------|-----------------|------|
| id           | str (uuid)      | chiave primaria |
| link         | str             | URL del reel Instagram |
| location_id  | str, FK         | riferimento a Location |
| note         | str, nullable   | breve descrizione/promemoria |
| types        | list[str]       | sottoinsieme della tassonomia (sezione 5); salvare come tabella di join `reel_type` oppure JSON in colonna, a scelta |
| created_at   | datetime        | default now |

### Tassonomia tipi (fissa, non nel DB — costante in `prompts.py`/`models.py`)
`food` 🍜, `culture` ⛩️, `nature` 🌸, `shopping` 🛍️, `stay` 🏨, `transport` 🚄, `experience` 🎡 — ognuno con label italiana, icona ed eventualmente un colore per la UI.

### Dati di seed (default alla prima creazione del DB)
Hub: Sapporo/Hokkaido, Sendai/Tohoku, Tokyo/Kanto, Nagoya/Chubu, Kyoto-Osaka/Kansai, Hiroshima/Chugoku, Matsuyama/Shikoku, Fukuoka/Kyushu, Okinawa.
Satelliti d'esempio: Nikko, Kamakura, Hakone, Kawagoe (→ Tokyo); Nara, Uji, Himeji (→ Kansai); Miyajima (→ Hiroshima); Otaru (→ Sapporo); Dazaifu (→ Fukuoka).
(Le coordinate x,y possono riprendere quelle già usate nel prototipo HTML, o essere ricalcolate.)

## 5. Funzionalità core

### 5.1 Mappa
- Endpoint che restituisce tutte le Location con relativo conteggio reel associati.
- Calcolo lato server (o client) della disposizione radiale dei satelliti attorno al proprio hub.
- Rendering SVG: stazioni-cerchio dimensionate in base al numero di reel, linee tratteggiate hub→satellite, click su una stazione che mostra il pannello con i reel di quella tappa.
- Filtro per tipo: chip cliccabili che attenuano le stazioni prive di reel del tipo selezionato.

### 5.2 Gestione reel (CRUD manuale)
- Form per aggiungere un reel: link, tappa (dropdown con hub raggruppati + relativi satelliti, opzione "crea nuova tappa"), tipo (multi-select), nota.
- Creazione di una nuova tappa al volo, sia come nuovo hub sia come satellite di un hub esistente.
- Eliminazione di un reel.

### 5.3 Categorizzazione assistita da AI

**Vincolo importante**: il servizio non può aprire il link Instagram (niente scraping/browsing). Lavora solo sul testo che l'utente fornisce (link + didascalia incollata, oppure una descrizione libera).

Flusso conversazionale (stateful per sessione, es. tenuto in memoria o in tabella `ai_session` con id sessione):

1. L'utente invia link + didascalia/descrizione.
2. Il backend costruisce i messaggi per l'SDK Anthropic con:
   - **system prompt**: spiega il compito, elenca gli hub esistenti (per permettere il match), definisce lo schema JSON di risposta.
   - **messages**: intera history della sessione (utente/assistente), non solo l'ultimo turno.
3. Il modello risponde **solo** con un JSON:
   ```json
   {
     "place_name": "string",
     "near_hub": "string | null",
     "types": ["food", "..."],
     "note": "string (max 20 parole)",
     "confidence": "high | medium | low",
     "question": "string | null"
   }
   ```
4. Se `question` è valorizzato, il backend lo mostra come messaggio dell'AI e attende la risposta dell'utente, poi richiama il modello con la history aggiornata.
5. Quando l'utente accetta la proposta ("Usa questo suggerimento"):
   - cerca una Location esistente il cui nome combacia con `place_name` (match case-insensitive, substring in entrambe le direzioni);
   - se non trovata ma `near_hub` combacia con un hub esistente, crea un satellite sotto quell'hub con nome `place_name`;
   - se `near_hub` è nullo e non c'è match, crea un nuovo hub;
   - precompila il form manuale (link, tappa, tipi, nota) così l'utente rivede e conferma prima di salvare — **non salvare mai automaticamente senza conferma**.
6. Filtra sempre `types` restituiti dal modello contro la tassonomia valida (ignora valori non riconosciuti).

### 5.4 Persistenza sessione AI
Da decidere in fase di implementazione: sessione in memoria del server (semplice, ok per single-user locale) oppure salvata su DB se si vuole sopravvivere a un riavvio del server a metà conversazione. Per un'app personale locale, la memoria di processo è sufficiente.

## 6. API (bozza endpoint REST)

| Metodo | Path                          | Descrizione |
|--------|-------------------------------|-------------|
| GET    | `/api/locations`              | lista location con conteggio reel |
| POST   | `/api/locations`               | crea location (hub o satellite) |
| DELETE | `/api/locations/{id}`         | elimina location (valutare cascata sui reel collegati) |
| GET    | `/api/reels?location_id=&type=` | lista reel filtrati |
| POST   | `/api/reels`                   | crea reel |
| DELETE | `/api/reels/{id}`              | elimina reel |
| POST   | `/api/ai/categorize`          | invia link+didascalia o risposta di follow-up, ritorna proposta AI (gestisce la sessione conversazionale) |

## 7. Direzione visiva (riferimento per il frontend)

Ispirazione: mappe ferroviarie giapponesi + estetica da stampa ukiyo-e/hanko.
- Colori: fondo carta washi grigio-caldo (`#E3E1D4`), inchiostro indigo profondo (`#1F2C47`), indigo medio per stazioni/linee (`#35496B`), rosso timbro hanko come unico accento per CTA e badge di conferma (`#A63A2E`), oro tenue per dettagli (`#B08D57`).
- Tipografia: display serif con influenza giapponese (es. Shippori Mincho) per i titoli, sans geometrico (es. Zen Kaku Gothic New) per il corpo, monospace per tag/contatori.
- La mappa è **schematica**, non geograficamente precisa: l'obiettivo è leggibilità del sistema hub→satellite, non accuratezza cartografica.

(Il prototipo HTML già realizzato può essere usato come riferimento diretto per markup/CSS da riadattare ai template Jinja2.)

## 8. Fuori scope (per ora)

- Multi-utente / autenticazione
- Import automatico dei reel salvati da Instagram (non esiste un modo affidabile/consentito per farlo)
- App mobile nativa
- Sincronizzazione cloud (si parte da SQLite locale; eventuale hosting è un passo successivo)

## 9. Possibile ordine di implementazione (per Claude Code)

1. Scaffold FastAPI + SQLModel + SQLite, modelli `Location`/`Reel`, seed data.
2. CRUD location e reel (senza AI), UI minima con Jinja2 per verificare il modello dati.
3. Rendering mappa SVG con layout radiale e filtri per tipo.
4. Form di aggiunta/eliminazione reel completo.
5. Integrazione AI: endpoint `/api/ai/categorize`, gestione sessione conversazionale, parsing JSON con fallback su errore.
6. Rifinitura visiva secondo la sezione 7.

## 10. Domande aperte da chiarire durante lo sviluppo

- Vuoi che l'app giri solo in locale (es. `uvicorn app.main:app --reload`) o pensi già a un piccolo deploy (Docker, Render, ecc.)?
- Preferisci salvare i tipi del reel come tabella di join relazionale o come colonna JSON semplice (più veloce da scrivere, meno "pulito")?
- La sessione di chat AI: va bene che si perda riavviando il server, o preferisci persisterla su DB?
