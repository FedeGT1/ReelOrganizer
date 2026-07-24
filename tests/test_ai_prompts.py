from app.ai.prompts import RESPONSE_SCHEMA, build_system_prompt
from app.taxonomy import VALID_TYPES


def test_response_schema_has_required_fields():
    assert RESPONSE_SCHEMA["required"] == [
        "place_name", "near_hub", "types", "note", "confidence", "question",
        "lat", "lon",
    ]
    assert RESPONSE_SCHEMA["additionalProperties"] is False


def test_response_schema_lat_lon_are_nullable_numbers():
    assert RESPONSE_SCHEMA["properties"]["lat"] == {"type": ["number", "null"]}
    assert RESPONSE_SCHEMA["properties"]["lon"] == {"type": ["number", "null"]}


def test_build_system_prompt_includes_hub_names():
    prompt = build_system_prompt(["Tokyo / Kanto", "Kyoto - Osaka / Kansai"])
    assert "Tokyo / Kanto" in prompt
    assert "Kyoto - Osaka / Kansai" in prompt


def test_build_system_prompt_mentions_lat_lon_estimation():
    prompt = build_system_prompt(["Tokyo / Kanto"])
    assert "lat" in prompt
    assert "lon" in prompt


def test_response_schema_types_items_are_constrained_to_the_taxonomy():
    # Regression: the model returned invented category names ("neighborhood",
    # "shopping district", ...) that never matched VALID_TYPES, so every
    # reel got saved with no type flags at all. The schema must constrain
    # each array item to exactly the app's taxonomy keys.
    items_schema = RESPONSE_SCHEMA["properties"]["types"]["items"]
    assert items_schema["type"] == "string"
    assert set(items_schema["enum"]) == VALID_TYPES


def test_build_system_prompt_lists_every_valid_type():
    prompt = build_system_prompt(["Tokyo / Kanto"])
    for key in VALID_TYPES:
        assert key in prompt


def test_build_system_prompt_pushes_for_approximate_estimate_over_hedging():
    # Regression: an earlier wording ("if you're not confident, leave lat/lon
    # null") let the model hedge even for well-known named places (e.g.
    # "Asakusa"). The prompt must now push for a best-effort approximate
    # estimate whenever a recognizable place is named in the text.
    prompt = build_system_prompt(["Tokyo / Kanto"])
    assert "approssimativa" in prompt
    assert "quartiere" in prompt
    assert "Asakusa" in prompt
