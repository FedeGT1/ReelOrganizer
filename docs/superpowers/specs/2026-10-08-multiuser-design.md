# Multiutente — Design

## Purpose

ReelOrganizer è oggi single-tenant: un solo login fisso (`AUTH_USERNAME`/`AUTH_PASSWORD` da env var), un solo set di hub/satelliti geografici, categorie e reel, condiviso da chiunque si autentichi. L'obiettivo è introdurre più account, ciascuno con i propri hub, categorie e reel, completamente isolati dagli altri utenti — mantenendo lo stesso deployment self-hosted su un'unica istanza/DB.

Il proprietario (unico admin) crea gli account a mano; non esiste registrazione pubblica. Al passaggio al multiutente, tutti i dati già presenti sul VPS vengono assegnati al proprio account, creato a partire dalle attuali `AUTH_USERNAME`/`AUTH_PASSWORD` — nessuna perdita di dati.

## Scope

**In scope:**
- Tabella `User` con password con hash, sostituendo il login a singolo utente fisso.
- `user_id` su `Location`, `Reel`, `AiSession`, `AskSession`; `Category` isolata per utente tramite chiave composita.
- Migrazione additiva (nessuna tabella ricreata, nessun dato cancellato) che assegna i dati esistenti al primo utente.
- Script CLI per creare nuovi utenti (admin-only, nessuna pagina di registrazione).
- Seed di hub/satelliti/categorie di default per ogni nuovo utente (oggi il seed gira una volta globalmente).
- Helper di scoping centralizzato usato da tutti i router per garantire che ogni query sia filtrata per utente corrente.

**Out of scope:**
- Registrazione self-service, invito via link/token, reset password via email (nessuna infrastruttura email nel progetto).
- Ruoli/permessi (admin vs utente normale) — ogni utente ha gli stessi diritti sui propri dati, nessuna gerarchia.
- Condivisione di dati tra utenti (es. un hub o un reel visibile a più account) — isolamento è sempre totale.
- Cambio della sessione da cookie firmato Starlette a uno store server-side — resta la stessa `SessionMiddleware` già in uso, solo il contenuto della sessione cambia.

## Modello dati e migrazione

### Nuova tabella `User`

```python
class User(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Colonne `user_id` aggiunte (additive, nullable)

- `Location.user_id`, `Reel.user_id`, `AiSession.user_id`, `AskSession.user_id` — FK verso `user.id`, aggiunte con lo stesso meccanismo già esistente in `app/db.py` (`_ADDITIVE_COLUMNS` + `ALTER TABLE ... ADD COLUMN`), così il DB sul VPS non viene mai ricreato.

### `Category`: chiave composita invece di PK singola

Oggi `Category.key` è la primary key globale (es. `"food"`). Con l'isolamento per utente, due utenti devono poter avere entrambi una categoria con chiave `"food"` senza collisione. `Category` passa a primary key composita `(user_id, key)`:

```python
class Category(SQLModel, table=True):
    user_id: str = Field(foreign_key="user.id", primary_key=True)
    key: str = Field(primary_key=True)
    label: str
    icon: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

`ReelType.type` resta una stringa semplice senza FK formale verso `category.key` (SQLite non impone di default i vincoli FK, e questa coppia non era comunque composita prima). L'isolamento resta garantito perché ogni accesso a `ReelType`/`Category` passa sempre per il filtro su `reel.user_id` / `category.user_id` lato applicazione — non serve rimappare righe esistenti di `ReelType`.

Poiché SQLite non supporta `ALTER TABLE` per cambiare una primary key su una tabella esistente, la migrazione di `Category` richiede ricreare la tabella (pattern "crea tabella nuova, copia righe, rinomina", tutto dentro la stessa transazione di avvio) invece di un semplice `ADD COLUMN`. Questo tocca solo `Category` — le altre tabelle usano `ADD COLUMN` come già oggi.

### Migrazione one-shot all'avvio

In `create_db_and_tables()` (o in un passo subito successivo nel `lifespan` di `main.py`):

1. Applica le colonne/tabelle additive come sopra.
2. Se la tabella `User` è vuota: crea un primo `User` con `username=AUTH_USERNAME`, `password_hash` calcolato da `AUTH_PASSWORD` (env var, lette una sola volta in questo momento).
3. Backfilla `user_id` (dove `NULL`) su tutte le righe esistenti di `Location`, `Reel`, `AiSession`, `AskSession` con l'id di questo utente; backfilla le righe di `Category` migrate con lo stesso `user_id`.

Questo passo è idempotente: se `User` non è vuoto (seconda esecuzione dopo la prima migrazione), i passi 2 e 3 vengono saltati.

## Autenticazione

- `verify_credentials(username, password)` smette di confrontare con le env var e interroga `User` per `username`, poi verifica `password_hash` con `hashlib.scrypt` (libreria standard — nessuna nuova dipendenza, rilevante per il VPS EOL con spazio/risorse limitate per compilare librerie native come bcrypt/argon2-cffi).
- Login: `request.session["user_id"] = user.id` sostituisce l'attuale `request.session["authenticated"] = True`.
- `AuthMiddleware`: controlla `request.session.get("user_id")` invece del flag booleano; se presente, instrada la request (i singoli router recuperano l'utente corrente dalla sessione quando devono filtrare le query).
- `AUTH_USERNAME`/`AUTH_PASSWORD` restano richieste all'avvio (`require_env`) solo per il bootstrap descritto sopra; dopo la prima migrazione il login usa esclusivamente `User` nel DB, le env var diventano ignorate (ma restano richieste per semplicità — evita un ramo di startup differente tra "prima volta" e "dopo").
- Il rate limiter (`RateLimiter`, chiavato per IP) resta identico: nessun cambiamento, protegge comunque il login indipendentemente da quale username viene tentato.

## Creazione utenti (admin-only)

Nuovo script `scripts/create_user.py`:
- Uso: `python -m scripts.create_user <username>`.
- Chiede la password in modo interattivo (`getpass`, non visibile a schermo, non passata come argomento per evitare che finisca nella history della shell).
- Verifica che lo username non esista già.
- Crea il `User`, poi chiama `seed_user_if_empty(session, user.id)` per popolare hub/satelliti/categorie di default per quel nuovo utente (vedi sotto).
- Nessuna pagina `/register` pubblica.

## Seed per-utente

`app/seed.py`: `seed_if_empty(session)` diventa `seed_user_if_empty(session, user_id)` — stessa logica (hub, satelliti, categorie di default), ma ogni riga creata porta `user_id=user_id`. Chiamato:
- Dallo script `create_user.py` alla creazione di un nuovo utente.
- Dalla migrazione one-shot per il primo utente bootstrap (invece di ri-seedare da zero, in quel caso si fa solo il backfill dei dati già esistenti — il seed per nuovo utente si applica solo a chi non ha ancora nulla).

## Scoping centralizzato

Nuovo modulo `app/scoping.py` con funzioni tipo:

```python
def user_locations(session, user_id) -> list[Location]: ...
def user_reels(session, user_id) -> list[Reel]: ...
def user_categories(session, user_id) -> list[Category]: ...
def get_owned(session, Model, id_, user_id) -> Model | None: ...
```

Ogni router (`locations.py`, `reels.py`, `categories.py`, `map.py`, `ai_ask.py`, `ai_categorize.py`, `ai_multi_categorize.py`, `audit.py`, `export.py`, `note_regeneration.py`, `instagram_import.py`) passa da `select(Model)` nudo a queste funzioni, e ogni creazione di riga (`Location(...)`, `Reel(...)`, ecc.) imposta `user_id` dall'utente corrente in sessione. Il lookup per id singolo (`get_owned`) ritorna `None` — tradotto in `404` uniforme — sia quando la riga non esiste sia quando appartiene a un altro utente, per non rivelare l'esistenza di id altrui.

Questo è l'unico punto da controllare per verificare che nessuna query dimentichi il filtro per utente — rischio altrimenti concreto con ~9 router e decine di query sparse.

## Error handling

- Login con utente inesistente o password sbagliata: stesso messaggio generico già esistente ("Credenziali non valide"), stesso status 401 — nessuna differenza di comportamento osservabile tra "utente non esiste" e "password sbagliata".
- Accesso a una risorsa (`Reel`, `Location`, ecc.) che esiste ma appartiene a un altro utente: `404`, non `403` — non si conferma l'esistenza della risorsa.
- Routing/pagine: nessun cambiamento alla logica attuale di redirect verso `/login` per richieste non autenticate (`AuthMiddleware`), solo il contenuto controllato in sessione cambia da booleano a `user_id`.

## Testing

- `app/scoping.py`: ogni funzione ritorna solo righe dell'utente corretto, dato un DB con dati di più utenti.
- Login con utenti reali in `User` (hash/verifica password), non più env var dirette.
- **Test di isolamento end-to-end** (il più importante): due utenti distinti, ciascuno crea hub/reel/categorie propri via API; si verifica che nessuno dei due veda, tramite nessun endpoint, i dati dell'altro — incluso il caso di accesso diretto per id a una risorsa di un altro utente (deve risultare 404).
- Test di migrazione: DB "vecchio" seedato senza `user_id` → dopo l'avvio, un solo `User` bootstrap esiste e tutte le righe pre-esistenti hanno quel `user_id`; seconda esecuzione della migrazione (riavvio) è no-op.
- Test della migrazione di `Category` (ricreazione tabella con nuova PK composita) su un DB con categorie pre-esistenti: nessuna riga persa, `(user_id, key)` risultante corretto.
- Test dello script `create_user.py`: crea l'utente, rifiuta username duplicati, esegue il seed per-utente.
