# Todo next step — idee per implementazioni future

Elenco di miglioramenti non urgenti, da valutare più avanti. Non sono specifiche pronte per l'implementazione, solo promemoria dell'idea e del perché potrebbe valere la pena farla.

## Multiutente

Oggi l'app è single-tenant: un solo set di hub, categorie e reel condiviso. L'idea è introdurre più utenti, ciascuno con i propri reel, hub e categorie personali (isolamento completo dei dati tra utenti).

**Perché potrebbe servire**: l'app ha già un sistema di login completo con rate limiting (non una semplice Basic Auth), quindi l'infrastruttura di autenticazione per-utente esiste già; manca solo il livello di isolamento dei dati.

**Nota implementativa**: è un cambiamento più ampio del primo — richiede una FK `user_id` su `Location`, `Reel`, `Category` (e forse `AiSession`/`AskSession`), oltre a filtrare tutte le query esistenti per utente corrente. Da trattare come progetto a parte con una sua brainstorming/design dedicata quando si deciderà di affrontarlo, non come piccola modifica incrementale.
