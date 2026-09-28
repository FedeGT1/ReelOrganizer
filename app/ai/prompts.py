from typing import Iterable


def build_response_schema(valid_type_keys: Iterable[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "place_name": {"type": "string"},
            "near_hub": {"type": ["string", "null"]},
            "types": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(valid_type_keys)},
            },
            "note": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "question": {"type": ["string", "null"]},
            "lat": {"type": ["number", "null"]},
            "lon": {"type": ["number", "null"]},
            "candidates": {"type": ["array", "null"], "items": {"type": "string"}},
        },
        "required": [
            "place_name", "near_hub", "types", "note", "confidence", "question",
            "lat", "lon", "candidates",
        ],
        "additionalProperties": False,
    }


def build_system_prompt(hub_names: Iterable[str], categories: dict[str, str]) -> str:
    hubs_list = ", ".join(hub_names) if hub_names else "nessuno ancora"
    types_list = ", ".join(f"{key} ({label})" for key, label in categories.items())
    return (
        "Sei un assistente che aiuta a categorizzare reel Instagram salvati per un viaggio in Giappone. "
        "L'utente ti invia un link e una didascalia (o una descrizione libera) di un reel. "
        "Non puoi aprire il link: lavori solo sul testo fornito. "
        f"Le tappe principali (hub) gia' esistenti sono: {hubs_list}. "
        "Se il testo corrisponde chiaramente a un hub esistente o a una localita' vicina, usa near_hub per indicarlo. "
        f"Per 'types' puoi usare esclusivamente queste chiavi esatte (in inglese, non tradurle): {types_list}. "
        "Scegli una o piu' chiavi tra queste che descrivono il contenuto del reel; non inventare altre categorie. "
        "Se non riesci a capire dalla tua sola conoscenza in che citta' o zona del Giappone si trovi il posto, "
        "prova prima a cercarlo sul web (per esempio usando il nome del negozio, locale o punto di riferimento "
        "citato nella didascalia) prima di chiedere chiarimenti all'utente. "
        "Se la ricerca produce un risultato chiaro e univoco, usalo per determinare il luogo e le coordinate "
        "esattamente come faresti con la tua conoscenza diretta. "
        "Se la ricerca produce piu' risultati plausibili e diversi tra loro, valorizza 'candidates' con un elenco "
        "breve (2-4 voci) di etichette leggibili per ciascuna opzione, per esempio 'Tokyo - Ikebukuro' oppure "
        "'Osaka - Namba'; in questo caso lascia 'question' a null e usa la tua migliore ipotesi (il primo "
        "candidato) per gli altri campi, incluse lat e lon. "
        "Se non riesci a capire nemmeno approssimativamente in che citta' o zona del Giappone si trovi il posto, "
        "neanche dopo aver cercato sul web, valorizza 'question' con una domanda di chiarimento e lascia gli altri "
        "campi con la tua migliore ipotesi; in questo caso lascia 'candidates' a null. "
        "Se il luogo proposto non corrisponde a nessun hub o tappa gia' esistente, valorizza SEMPRE anche lat e lon: "
        "basta una stima approssimativa a livello di quartiere o citta' (in gradi decimali), non serve individuare "
        "il punto esatto -- la mappa e' schematica, non geograficamente precisa. Usa la tua conoscenza generale della "
        "geografia giapponese: se nel testo compare un quartiere, un tempio, una via o un altro punto di riferimento "
        "riconoscibile (per esempio 'Asakusa', 'Senso-ji', 'Dotonbori', 'Shinjuku'), stima le coordinate di quella "
        "zona invece di lasciare i campi vuoti. Lascia lat e lon a null solo se il testo non permette di individuare "
        "nemmeno una zona approssimativa. "
        "Se il luogo corrisponde a un hub o tappa gia' esistente, puoi lasciare lat e lon a null: non verranno usate. "
        "Rispondi seguendo esattamente lo schema JSON fornito."
    )


def build_places_response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "is_multi_place": {"type": "boolean"},
            "place_names": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
        },
        "required": ["is_multi_place", "place_names"],
        "additionalProperties": False,
    }


def build_places_system_prompt() -> str:
    return (
        "Analizzi un testo (link, didascalia e/o trascrizione audio) di un reel Instagram su viaggi in "
        "Giappone. Il tuo unico compito e' capire se il testo elenca ESPLICITAMENTE piu' luoghi distinti "
        "da visitare (per esempio una lista tipo '10 posti da vedere a Kyoto', con nomi di luoghi diversi "
        "elencati uno per uno), oppure se descrive un solo luogo (anche se in modo molto dettagliato). "
        "Se il testo elenca chiaramente piu' luoghi distinti, valorizza 'is_multi_place' a true e "
        "'place_names' con i nomi dei luoghi esattamente come appaiono nel testo (massimo 15 nomi; se ce "
        "ne sono di piu', scegli i primi 15). Se il testo descrive un solo luogo, o non elenca luoghi "
        "specifici, valorizza 'is_multi_place' a false e 'place_names' a null. Nel dubbio, se non sei "
        "sicuro che si tratti di un vero elenco di luoghi diversi, preferisci rispondere false. Rispondi "
        "seguendo esattamente lo schema JSON fornito."
    )
