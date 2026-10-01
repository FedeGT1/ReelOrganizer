import markdown
import nh3
from markupsafe import Markup

ALLOWED_TAGS = {
    "p", "strong", "em", "a", "ul", "ol", "li",
    "code", "pre", "blockquote", "br", "h3", "h4", "h5", "h6", "hr",
}
ALLOWED_ATTRIBUTES = {"a": {"href"}}
ALLOWED_URL_SCHEMES = {"http", "https"}


def render_answer_markdown(text: str) -> Markup:
    html = markdown.markdown(text)
    clean_html = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        set_tag_attribute_values={"a": {"target": "_blank"}},
    )
    return Markup(clean_html)
