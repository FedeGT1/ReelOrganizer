from app.taxonomy import TAXONOMY, VALID_TYPES


def test_taxonomy_has_seven_fixed_types():
    assert VALID_TYPES == {
        "food", "culture", "nature", "shopping", "stay", "transport", "experience",
    }


def test_every_type_has_label_icon_and_color():
    for type_key, info in TAXONOMY.items():
        assert "label" in info
        assert "icon" in info
        assert "color" in info
