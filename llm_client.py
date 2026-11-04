"""Small OpenAI-compatible client for an on-premise language model.

The client deliberately uses the Python standard library so the review agent
does not require an external SDK or send documents to a cloud provider.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib import error, request


class LLMConfigurationError(RuntimeError):
    """Raised when the internal model endpoint is not configured."""


class LLMRequestError(RuntimeError):
    """Raised when the internal model endpoint returns an error."""


@dataclass(frozen=True)
class LLMClient:
    """Call an OpenAI-compatible chat-completions endpoint.

    Set ``INTERNAL_LLM_BASE_URL`` to the internal service URL, for example
    ``http://llm-server:8000/v1``.  No API key is required when the service is
    protected by the test network, but ``INTERNAL_LLM_API_KEY`` is supported.
    """

    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: int = 120

    @classmethod
    def from_environment(cls) -> "LLMClient":
        base_url = os.getenv("INTERNAL_LLM_BASE_URL", "").strip()
        model = os.getenv("INTERNAL_LLM_MODEL", "").strip()
        if not base_url or not model:
            raise LLMConfigurationError(
                "Set INTERNAL_LLM_BASE_URL and INTERNAL_LLM_MODEL before review."
            )
        timeout = int(os.getenv("INTERNAL_LLM_TIMEOUT_SECONDS", "120"))
        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=os.getenv("INTERNAL_LLM_API_KEY") or None,
            timeout_seconds=timeout,
        )

    def complete(self, messages: list[dict[str, str]], temperature: float = 0.0) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMRequestError(f"Internal LLM returned HTTP {exc.code}: {detail}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise LLMRequestError(f"Could not reach the internal LLM: {exc}") from exc

        try:
            return body["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMRequestError("Internal LLM response has no chat completion content") from exc
