# Todo next step — idee per implementazioni future

Elenco di miglioramenti non urgenti, da valutare più avanti. Non sono specifiche pronte per l'implementazione, solo promemoria dell'idea e del perché potrebbe valere la pena farla.

## Campo titolo nel form di aggiunta reel manuale

Il form manuale (`app/templates/partials/reel_add_form.html`) non ha un campo titolo/nome per il reel: oggi si sceglie solo una location *già esistente* da una tendina, una nota opzionale e le categorie. A differenza del flusso AI (che propone liberamente un `place_name` e può crearne una nuova), dal form manuale non si può né dare un titolo distinto all'aggiunta né creare una location nuova al volo — serve prima passare da "Gestisci hub".

**Perché potrebbe servire**: coerenza con il flusso AI e più comodità nell'uso quotidiano (non dover uscire dal flusso di aggiunta reel per creare prima la location).

**Nota implementativa**: da chiarire in design se "titolo" significa un campo libero sul `Reel` stesso (richiederebbe una nuova colonna, es. `title` — modifica additiva allo schema, nessun rischio per i dati esistenti) oppure semplicemente la possibilità di digitare/creare al volo una nuova location dal form stesso (nessuna modifica di schema, solo UX che replica la logica già usata dal flusso AI).

## Avviso quando si aggiunge un reel già presente

Oggi `Reel.link` (`app/models.py`) non ha alcun vincolo di unicità: niente impedisce di salvare due volte lo stesso link Instagram, né manualmente né tramite il flusso AI — e l'app non controlla mai se il link è già stato salvato prima di crearne un altro.

**Perché potrebbe servire**: evitare doppioni involontari (es. ri-aggiungere per sbaglio un reel visto tempo prima e dimenticato, o re-importarlo dopo che Instagram lo ripropone nel feed).

**Nota implementativa**: un controllo per link esatto è semplice (query su `Reel.link` prima di creare), ma non copre varianti dello stesso link (query string diverse, `instagram.com` vs `www.instagram.com`, reel condiviso vs link diretto) — da valutare se normalizzare il link (es. solo lo shortcode del reel) prima del confronto. Da decidere anche se bloccare il salvataggio o solo avvisare con un "lo hai già salvato, vuoi procedere comunque?" (coerente con l'approccio "segnala, non bloccare silenziosamente" usato altrove).

## Salvare didascalia + trascrizione audio del reel

Oggi (vedi `app/routers/ai_categorize.py` e `app/routers/ai_multi_categorize.py`) la didascalia Instagram e la trascrizione audio (Whisper) vengono usate solo per pre-compilare la chat con l'AI: vivono temporaneamente come `AiMessage.content`, ma al salvataggio del reel confermato vengono cancellate insieme alla sessione AI. Il modello `Reel` (`app/models.py`) conserva solo `note` (il riassunto scritto dall'AI), non il testo originale.

**Perché potrebbe servire**: permetterebbe di rigenerare la `note` in futuro con un prompt migliorato senza dover ri-scaricare/ri-trascrivere il reel, e sarebbe utile per debug quando una categorizzazione sembra sbagliata.

**Nota implementativa**: richiede nuove colonne (es. `caption`, `transcript`) su `Reel` — modifica additiva allo schema, nessun rischio per i dati esistenti sulla VPS.

## Rigenerare le note (singola o massiva)

Possibilità di rigenerare la `note` di un reel già salvato — sia singolarmente (es. un bottone "rigenera" sulla card del reel) sia in massa su tutti i reel esistenti — richiamando di nuovo l'AI con il prompt aggiornato.

**Perché potrebbe servire**: quando il prompt di categorizzazione viene migliorato (come fatto il 2026-10-02, per note più ricche e senza riferimenti al reel), i reel già salvati restano con la vecchia nota; questa funzione permetterebbe di aggiornarli senza ripetere a mano l'intero flusso di categorizzazione.

**Nota implementativa**: dipende dal punto precedente (salvare didascalia + trascrizione) — senza il testo originale conservato, la rigenerazione massiva potrebbe solo ripartire dalla `note` attuale invece che dalla fonte originale, con risultati meno affidabili. Da valutare anche costo/tempo delle chiamate AI per la rigenerazione massiva su molti reel.

## Multiutente

Oggi l'app è single-tenant: un solo set di hub, categorie e reel condiviso. L'idea è introdurre più utenti, ciascuno con i propri reel, hub e categorie personali (isolamento completo dei dati tra utenti).

**Perché potrebbe servire**: l'app ha già un sistema di login completo con rate limiting (non una semplice Basic Auth), quindi l'infrastruttura di autenticazione per-utente esiste già; manca solo il livello di isolamento dei dati.

**Nota implementativa**: è un cambiamento più ampio del primo — richiede una FK `user_id` su `Location`, `Reel`, `Category` (e forse `AiSession`/`AskSession`), oltre a filtrare tutte le query esistenti per utente corrente. Da trattare come progetto a parte con una sua brainstorming/design dedicata quando si deciderà di affrontarlo, non come piccola modifica incrementale.
