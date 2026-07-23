from app.ai.prompts import RESPONSE_SCHEMA, build_system_prompt


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
