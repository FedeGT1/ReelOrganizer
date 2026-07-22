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
    },
    "required": ["place_name", "near_hub", "types", "note", "confidence", "question"],
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
        "Se non hai abbastanza informazioni per proporre un luogo con sicurezza, valorizza 'question' con una domanda "
        "di chiarimento e lascia gli altri campi con la tua migliore ipotesi. "
        "Rispondi seguendo esattamente lo schema JSON fornito."
    )
