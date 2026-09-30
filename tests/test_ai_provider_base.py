from app.ai.providers.base import AIProviderError


def test_ai_provider_error_is_an_exception_with_message():
    err = AIProviderError("boom")
    assert isinstance(err, Exception)
    assert str(err) == "boom"
