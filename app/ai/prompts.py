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
        },
        "required": [
            "place_name", "near_hub", "types", "note", "confidence", "question",
            "lat", "lon",
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
