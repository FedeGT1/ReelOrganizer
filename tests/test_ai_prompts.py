from app.ai.prompts import build_response_schema, build_system_prompt, build_ask_response_schema, build_ask_system_prompt

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


SAMPLE_REELS = [
    {"place_name": "Ichiran Ramen", "categories": ["Cibo"], "note": "Ramen famoso", "link": "https://instagram.com/reel/abc"},
    {"place_name": "Nikko", "categories": ["Natura", "Cultura"], "note": "", "link": "https://instagram.com/reel/def"},
]


def test_ask_response_schema_requires_answer_only():
    schema = build_ask_response_schema()
    assert schema["properties"] == {"answer": {"type": "string"}}
    assert schema["required"] == ["answer"]
    assert schema["additionalProperties"] is False


def test_ask_system_prompt_includes_reel_place_names_and_links():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", None, False)
    assert "Ichiran Ramen" in prompt
    assert "Nikko" in prompt
    assert "https://instagram.com/reel/abc" in prompt
    assert "https://instagram.com/reel/def" in prompt


def test_ask_system_prompt_mentions_active_city_and_category_filter():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", "Cibo", False)
    assert "Tokyo / Kanto" in prompt
    assert "Cibo" in prompt


def test_ask_system_prompt_states_no_filter_when_both_are_none():
    prompt = build_ask_system_prompt(SAMPLE_REELS, None, None, False)
    assert "nessun filtro" in prompt.lower()


def test_ask_system_prompt_states_no_reels_when_list_is_empty():
    prompt = build_ask_system_prompt([], "Osaka", None, False)
    assert "nessun reel" in prompt.lower()


def test_ask_system_prompt_warns_about_truncation_when_flagged():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", None, True)
    assert "parziale" in prompt.lower()


def test_ask_system_prompt_omits_truncation_warning_when_not_flagged():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", None, False)
    assert "parziale" not in prompt.lower()


def test_ask_system_prompt_prioritizes_saved_reels_over_web_search():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", None, False)
    assert "priorita" in prompt.lower()
    assert "web" in prompt.lower()


def test_ask_system_prompt_encourages_markdown_bold_and_links():
    # The chat UI renders 'answer' through a markdown-to-HTML pipeline
    # (app/ai/answer_markdown.py) with links made clickable, so -- unlike
    # the categorization chat's plain-text 'note' field -- this prompt
    # should actively invite markdown formatting and markdown-style
    # citation links rather than forbid them.
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", None, False)
    assert "markdown" in prompt.lower()
    assert "**" in prompt
    assert "[testo](url)" in prompt
