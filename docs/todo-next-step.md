# Todo next step — idee per implementazioni future

Elenco di miglioramenti non urgenti, da valutare più avanti. Non sono specifiche pronte per l'implementazione, solo promemoria dell'idea e del perché potrebbe valere la pena farla.

## Importare anche da TikTok, non solo Instagram

Oggi il flusso di importazione AI (`app/routers/instagram_import.py`) accetta solo link Instagram (`_is_instagram_link` controlla l'hostname `instagram.com`/`www.instagram.com`). L'idea è permettere di importare — scaricare, trascrivere e categorizzare — anche video TikTok con lo stesso flusso.

**Perché potrebbe servire**: non tutti i contenuti salvati arrivano da Instagram; poter incollare un link TikTok e avere lo stesso comodo flusso (download, trascrizione, categorizzazione AI) eviterebbe di dover inserire quei reel a mano.

**Nota implementativa**: il download (`app/ingest/instagram.py`) usa già `yt-dlp`, che supporta nativamente TikTok, quindi la parte di fetch/trascrizione potrebbe richiedere pochi cambi. Da verificare: se TikTok richiede cookie di autenticazione come Instagram (vedi lo strumento "Cookie Instagram" — potrebbe servirne uno analogo), se l'estrazione della didascalia dai metadati yt-dlp è compatibile, e se vale la pena generalizzare `_is_instagram_link`/il nome del modulo `instagram.py` in qualcosa di più neutro ora che gestirebbe più piattaforme.
