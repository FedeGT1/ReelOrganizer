from app.ai.prompts import RESPONSE_SCHEMA, build_system_prompt


def test_response_schema_has_required_fields():
    assert RESPONSE_SCHEMA["required"] == [
        "place_name", "near_hub", "types", "note", "confidence", "question",
    ]
    assert RESPONSE_SCHEMA["additionalProperties"] is False


def test_build_system_prompt_includes_hub_names():
    prompt = build_system_prompt(["Tokyo / Kanto", "Kyoto - Osaka / Kansai"])
    assert "Tokyo / Kanto" in prompt
    assert "Kyoto - Osaka / Kansai" in prompt
