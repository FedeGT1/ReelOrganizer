# Todo next step — idee per implementazioni future

Elenco di miglioramenti non urgenti, da valutare più avanti. Non sono specifiche pronte per l'implementazione, solo promemoria dell'idea e del perché potrebbe valere la pena farla.

## Importare anche da TikTok, non solo Instagram

Oggi il flusso di importazione AI (`app/routers/instagram_import.py`) accetta solo link Instagram (`_is_instagram_link` controlla l'hostname `instagram.com`/`www.instagram.com`). L'idea è permettere di importare — scaricare, trascrivere e categorizzare — anche video TikTok con lo stesso flusso.

**Perché potrebbe servire**: non tutti i contenuti salvati arrivano da Instagram; poter incollare un link TikTok e avere lo stesso comodo flusso (download, trascrizione, categorizzazione AI) eviterebbe di dover inserire quei reel a mano.

**Nota implementativa**: il download (`app/ingest/instagram.py`) usa già `yt-dlp`, che supporta nativamente TikTok, quindi la parte di fetch/trascrizione potrebbe richiedere pochi cambi. Da verificare: se TikTok richiede cookie di autenticazione come Instagram (vedi lo strumento "Cookie Instagram" — potrebbe servirne uno analogo), se l'estrazione della didascalia dai metadati yt-dlp è compatibile, e se vale la pena generalizzare `_is_instagram_link`/il nome del modulo `instagram.py` in qualcosa di più neutro ora che gestirebbe più piattaforme.

## Multiutente

Oggi l'app è single-tenant: un solo set di hub, categorie e reel condiviso. L'idea è introdurre più utenti, ciascuno con i propri reel, hub e categorie personali (isolamento completo dei dati tra utenti).

**Perché potrebbe servire**: l'app ha già un sistema di login completo con rate limiting (non una semplice Basic Auth), quindi l'infrastruttura di autenticazione per-utente esiste già; manca solo il livello di isolamento dei dati.

**Nota implementativa**: è un cambiamento più ampio del primo — richiede una FK `user_id` su `Location`, `Reel`, `Category` (e forse `AiSession`/`AskSession`), oltre a filtrare tutte le query esistenti per utente corrente. Da trattare come progetto a parte con una sua brainstorming/design dedicata quando si deciderà di affrontarlo, non come piccola modifica incrementale.
