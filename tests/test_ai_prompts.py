from app.ai.prompts import build_response_schema, build_system_prompt

VALID_TYPES = {"food", "culture", "nature", "shopping", "stay", "transport", "experience"}
CATEGORIES = {
    "food": "Cibo",
    "culture": "Cultura",
    "nature": "Natura",
    "shopping": "Shopping",
    "stay": "Alloggio",
    "transport": "Trasporti",
    "experience": "Esperienza",
}


def test_response_schema_has_required_fields():
    schema = build_response_schema(VALID_TYPES)
    assert schema["required"] == [
        "place_name", "near_hub", "types", "note", "confidence", "question",
        "lat", "lon", "candidates",
    ]
    assert schema["additionalProperties"] is False


def test_response_schema_candidates_is_nullable_array_of_strings():
    schema = build_response_schema(VALID_TYPES)
    assert schema["properties"]["candidates"] == {
        "type": ["array", "null"],
        "items": {"type": "string"},
    }


def test_response_schema_lat_lon_are_nullable_numbers():
    schema = build_response_schema(VALID_TYPES)
    assert schema["properties"]["lat"] == {"type": ["number", "null"]}
    assert schema["properties"]["lon"] == {"type": ["number", "null"]}


def test_response_schema_types_items_are_constrained_to_the_given_types():
    schema = build_response_schema(VALID_TYPES)
    items_schema = schema["properties"]["types"]["items"]
    assert items_schema["type"] == "string"
    assert set(items_schema["enum"]) == VALID_TYPES


def test_build_system_prompt_includes_hub_names():
    prompt = build_system_prompt(["Tokyo / Kanto", "Kyoto - Osaka / Kansai"], CATEGORIES)
    assert "Tokyo / Kanto" in prompt
    assert "Kyoto - Osaka / Kansai" in prompt


def test_build_system_prompt_mentions_lat_lon_estimation():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    assert "lat" in prompt
    assert "lon" in prompt


def test_build_system_prompt_lists_every_given_category():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    for key in CATEGORIES:
        assert key in prompt


def test_build_system_prompt_reflects_custom_categories():
    # Regression guard for the whole point of this feature: a category the
    # user just created must show up in the prompt exactly like a built-in
    # one, with no special-casing.
    prompt = build_system_prompt(["Tokyo / Kanto"], {"nightlife": "Vita notturna"})
    assert "nightlife" in prompt
    assert "Vita notturna" in prompt


def test_build_system_prompt_pushes_for_approximate_estimate_over_hedging():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    assert "approssimativa" in prompt
    assert "quartiere" in prompt
    assert "Asakusa" in prompt


def test_build_system_prompt_instructs_web_search_before_asking_user():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    assert "cerca" in prompt.lower()


def test_build_system_prompt_explains_candidates_field_for_ambiguous_search():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    assert "candidates" in prompt
    assert "question" in prompt


def test_build_system_prompt_forbids_citations_and_links_in_note():
    # Regression guard: some providers' web-search tools (observed with
    # GPT-6 Luna) default to embedding inline markdown citations like
    # "([kyoto-tower.jp](https://...?utm_source=openai))" into generated
    # text once search results are involved. Nothing told the model what
    # 'note' should look like, so it fell back to that habit. The prompt
    # must say explicitly: plain text, no links/citations, in 'note'.
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    assert "note" in prompt
    assert "link" in prompt.lower()
    assert "citazion" in prompt.lower()
