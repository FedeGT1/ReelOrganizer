from typing import Iterable

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "place_name": {"type": "string"},
        "near_hub": {"type": ["string", "null"]},
        "types": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "question": {"type": ["string", "null"]},
        "lat": {"type": ["number", "null"]},
        "lon": {"type": ["number", "null"]},
    },
    "required": [
        "place_name", "near_hub", "types", "note", "confidence", "question",
        "lat", "lon",
    ],
    "additionalProperties": False,
}


def build_system_prompt(hub_names: Iterable[str]) -> str:
    hubs_list = ", ".join(hub_names) if hub_names else "nessuno ancora"
    return (
        "Sei un assistente che aiuta a categorizzare reel Instagram salvati per un viaggio in Giappone. "
        "L'utente ti invia un link e una didascalia (o una descrizione libera) di un reel. "
        "Non puoi aprire il link: lavori solo sul testo fornito. "
        f"Le tappe principali (hub) gia' esistenti sono: {hubs_list}. "
        "Se il testo corrisponde chiaramente a un hub esistente o a una localita' vicina, usa near_hub per indicarlo. "
        "Se non riesci a capire nemmeno approssimativamente in che citta' o zona del Giappone si trovi il posto, "
        "valorizza 'question' con una domanda di chiarimento e lascia gli altri campi con la tua migliore ipotesi. "
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
