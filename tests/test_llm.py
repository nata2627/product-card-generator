import json
import time

import httpx
import pytest

from card_generator.llm import CHAT_URL, OAUTH_URL, GigaChatClient, LLMError

SECRET_KEY = "c2VjcmV0LWtleQ=="
TOKEN = "token-123"


def _token_response():
    expires = int((time.time() + 1800) * 1000)
    return httpx.Response(200, json={"access_token": TOKEN, "expires_at": expires})


def _chat_response(text="ответ"):
    return httpx.Response(
        200,
        json={
            "model": "GigaChat-2-Max",
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def make_client(tmp_path, chat_responses, oauth_status=200):
    calls = {"oauth": 0, "chat": 0}
    chat_iter = iter(chat_responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_URL:
            calls["oauth"] += 1
            if oauth_status != 200:
                return httpx.Response(oauth_status)
            return _token_response()
        assert str(request.url) == CHAT_URL
        calls["chat"] += 1
        item = next(chat_iter)
        if isinstance(item, Exception):
            raise item
        return item

    client = GigaChatClient(
        auth_key=SECRET_KEY,
        token_cache=tmp_path / "token.json",
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
    )
    return client, calls


def complete(client):
    return client.complete([{"role": "user", "content": "привет"}])


def test_success_returns_text_and_usage(tmp_path):
    client, calls = make_client(tmp_path, [_chat_response("карточка")])
    result = complete(client)
    assert result.text == "карточка"
    assert (result.prompt_tokens, result.completion_tokens) == (10, 5)
    assert calls == {"oauth": 1, "chat": 1}


def test_token_is_cached_between_calls(tmp_path):
    client, calls = make_client(tmp_path, [_chat_response(), _chat_response()])
    complete(client)
    complete(client)
    assert calls["oauth"] == 1
    assert json.loads((tmp_path / "token.json").read_text())["access_token"] == TOKEN


def test_expired_token_is_refreshed_once(tmp_path):
    client, calls = make_client(tmp_path, [httpx.Response(401), _chat_response()])
    assert complete(client).text == "ответ"
    assert calls == {"oauth": 2, "chat": 2}


def test_retries_on_429_and_5xx_then_succeeds(tmp_path):
    client, calls = make_client(
        tmp_path, [httpx.Response(429), httpx.Response(503), _chat_response()]
    )
    assert complete(client).text == "ответ"
    assert calls["chat"] == 3


def test_gives_up_after_three_attempts(tmp_path):
    client, calls = make_client(tmp_path, [httpx.Response(500)] * 3)
    with pytest.raises(LLMError, match="HTTP 500"):
        complete(client)
    assert calls["chat"] == 3


def test_missing_key_has_readable_error():
    with pytest.raises(LLMError, match="GIGACHAT_AUTH_KEY"):
        GigaChatClient(auth_key="", transport=httpx.MockTransport(lambda r: None))


def test_rejected_key_does_not_leak_key(tmp_path):
    client, _ = make_client(tmp_path, [], oauth_status=401)
    with pytest.raises(LLMError) as err:
        complete(client)
    assert "не принял ключ" in str(err.value)
    assert SECRET_KEY not in str(err.value)


def test_timeout_has_readable_error(tmp_path):
    client, _ = make_client(tmp_path, [httpx.ReadTimeout("slow")])
    with pytest.raises(LLMError, match="не ответил вовремя"):
        complete(client)


def test_ssl_error_points_to_certificate_step(tmp_path):
    error = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    client, _ = make_client(tmp_path, [error])
    with pytest.raises(LLMError, match="сертификат"):
        complete(client)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, text="not json"),
        _chat_response("   "),
    ],
)
def test_malformed_or_empty_response(tmp_path, response):
    client, _ = make_client(tmp_path, [response])
    with pytest.raises(LLMError):
        complete(client)
