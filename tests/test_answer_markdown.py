from markupsafe import Markup

from app.ai.answer_markdown import render_answer_markdown


def test_renders_bold_text():
    result = render_answer_markdown("Ti consiglio **Asakusa** per i templi.")
    assert "<strong>Asakusa</strong>" in result


def test_renders_markdown_link_as_clickable_anchor():
    result = render_answer_markdown("Fonte: [gotokyo.org](https://www.gotokyo.org/en/asakusa/)")
    assert '<a href="https://www.gotokyo.org/en/asakusa/"' in result
    assert "gotokyo.org</a>" in result


def test_links_open_in_new_tab_with_safe_rel():
    result = render_answer_markdown("[link](https://example.com)")
    assert 'target="_blank"' in result
    assert 'rel="noopener noreferrer"' in result


def test_returns_markup_safe_for_direct_template_use():
    result = render_answer_markdown("testo semplice")
    assert isinstance(result, Markup)


def test_strips_script_tags_and_their_content():
    result = render_answer_markdown("prima <script>alert(1)</script> dopo")
    assert "<script>" not in result
    assert "alert(1)" not in result
    assert "prima" in result and "dopo" in result


def test_strips_javascript_scheme_from_links():
    result = render_answer_markdown("[click](javascript:alert(1))")
    assert "javascript:" not in result


def test_strips_disallowed_tags_like_img_with_event_handlers():
    result = render_answer_markdown('testo <img src=x onerror="alert(1)"> fine')
    assert "<img" not in result
    assert "onerror" not in result
    assert "testo" in result and "fine" in result


def test_plain_text_without_markdown_renders_cleanly():
    result = render_answer_markdown("Nessun reel corrisponde a questo filtro.")
    assert "Nessun reel corrisponde a questo filtro." in result
