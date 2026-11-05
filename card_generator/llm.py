"""GigaChat chat client: OAuth token with a file cache, retries and readable errors.

The rest of the service talks to any object with ``complete(messages)``, so a
local OpenAI-compatible model or a test double can replace this class.
"""

import json
import os
import ssl
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
DEFAULT_MODEL = "GigaChat-2-Max"
DEFAULT_CERT = ROOT / "certs" / "russian_trusted_root_ca.pem"
DEFAULT_TOKEN_CACHE = ROOT / ".cache" / "gigachat_token.json"
MAX_ATTEMPTS = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}


class LLMError(Exception):
    """An error the user can act on; the message is shown as is and never holds secrets."""


@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float


class LLM(Protocol):
    def complete(self, messages: list[dict]) -> Completion: ...


class GigaChatClient:
    def __init__(
        self,
        auth_key: str,
        model: str = DEFAULT_MODEL,
        scope: str = "GIGACHAT_API_PERS",
        temperature: float = 0.1,
        timeout_s: float = 60.0,
        cert_path: Path = DEFAULT_CERT,
        token_cache: Path = DEFAULT_TOKEN_CACHE,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not auth_key:
            raise LLMError("Нет ключа GIGACHAT_AUTH_KEY. Заполните .env по README, шаг 3.")
        self.model = model
        self.temperature = temperature
        self._auth_key = auth_key
        self._scope = scope
        self._token_cache = token_cache
        self._sleep = sleep
        if transport is None:
            if not cert_path.exists():
                raise LLMError(
                    f"Нет сертификата {cert_path.relative_to(ROOT)}. Скачайте его по README, шаг 2."
                )
            verify: ssl.SSLContext | bool = ssl.create_default_context(cafile=str(cert_path))
        else:
            verify = True
        self._http = httpx.Client(timeout=timeout_s, verify=verify, transport=transport)

    @classmethod
    def from_env(cls, **kwargs) -> "GigaChatClient":
        load_dotenv(ROOT / ".env")
        return cls(
            auth_key=os.getenv("GIGACHAT_AUTH_KEY", "").strip(),
            model=os.getenv("GIGACHAT_MODEL", DEFAULT_MODEL),
            scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            **kwargs,
        )

    def complete(self, messages: list[dict]) -> Completion:
        body = {"model": self.model, "messages": messages, "temperature": self.temperature}
        started = time.monotonic()
        response = self._post_chat(body)
        try:
            data = response.json()
            choice = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("GigaChat вернул ответ неожиданного формата.") from exc
        if not choice or not choice.strip():
            raise LLMError("GigaChat вернул пустой ответ.")
        usage = data.get("usage") or {}
        return Completion(
            text=choice,
            model=data.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_s=round(time.monotonic() - started, 2),
        )

    def _post_chat(self, body: dict) -> httpx.Response:
        refreshed = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            headers = {"Authorization": f"Bearer {self._token()}"}
            response = self._send("POST", CHAT_URL, json=body, headers=headers)
            if response.status_code == 401 and not refreshed:
                # Token expired or revoked earlier than its expires_at: fetch a new one once.
                self._token_cache.unlink(missing_ok=True)
                refreshed = True
                continue
            if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                self._sleep(2.0 * attempt)
                continue
            if response.status_code != 200:
                raise LLMError(f"GigaChat ответил HTTP {response.status_code}.")
            return response
        raise LLMError(f"GigaChat не ответил после {MAX_ATTEMPTS} попыток.")

    def _token(self) -> str:
        if self._token_cache.exists():
            try:
                cached = json.loads(self._token_cache.read_text())
                if cached["expires_at"] / 1000 - time.time() > 60:
                    return cached["access_token"]
            except (ValueError, KeyError):
                pass  # a broken cache is the same as no cache
        response = self._send(
            "POST",
            OAUTH_URL,
            data={"scope": self._scope},
            headers={
                "Authorization": f"Basic {self._auth_key}",
                "RqUID": str(uuid.uuid4()),
                "Accept": "application/json",
            },
        )
        if response.status_code in (400, 401, 403):
            raise LLMError(
                f"GigaChat не принял ключ (OAuth HTTP {response.status_code}). "
                "Проверьте GIGACHAT_AUTH_KEY и GIGACHAT_SCOPE в .env."
            )
        if response.status_code != 200:
            raise LLMError(f"Сервер авторизации GigaChat ответил HTTP {response.status_code}.")
        token = response.json()
        self._token_cache.parent.mkdir(parents=True, exist_ok=True)
        self._token_cache.write_text(
            json.dumps({"access_token": token["access_token"], "expires_at": token["expires_at"]})
        )
        self._token_cache.chmod(0o600)
        return token["access_token"]

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise LLMError("GigaChat не ответил вовремя, попробуйте еще раз.") from exc
        except httpx.ConnectError as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                raise LLMError(
                    "Ошибка SSL: нужен корневой сертификат Минцифры, см. README, шаг 2."
                ) from exc
            raise LLMError("Нет соединения с GigaChat.") from exc
