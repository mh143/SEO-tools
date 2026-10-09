"""AI provider abstraction.

Providers take a system prompt, an untrusted-data user message, and a JSON schema, and must return
a dict that is then validated again by our own code (never trusted blindly).

* ``anthropic`` — Claude via the official SDK with structured outputs (output_config.format).
* ``mock``      — deterministic, offline provider for tests and demos. Refused in production and
                  every result is labelled ``generator="ai:mock"`` so it can never pass as real AI output.
* ``none``      — AI features report "not configured".
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import get_settings

log = logging.getLogger(__name__)


class AIError(Exception):
    pass


class AINotConfigured(AIError):
    pass


@dataclass
class AIResult:
    data: dict[str, Any]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class AIProvider(Protocol):
    name: str

    def generate(self, *, task: str, system: str, user: str, schema: dict) -> AIResult: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic

        s = get_settings()
        if not s.anthropic_api_key:
            raise AINotConfigured("ANTHROPIC_API_KEY is not set.")
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=120.0, max_retries=2)
        self.model = s.anthropic_model

    def generate(self, *, task: str, system: str, user: str, schema: dict) -> AIResult:
        s = get_settings()
        a = self._anthropic
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=s.ai_max_output_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": s.ai_effort, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            if s.ai_refusal_fallback:
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except a.RateLimitError as exc:
            raise AIError("The AI provider is rate limiting requests. Try again shortly.") from exc
        except a.AuthenticationError as exc:
            raise AINotConfigured("The AI provider rejected the API key.") from exc
        except a.BadRequestError as exc:
            raise AIError(f"The AI provider rejected the request: {exc.message}") from exc
        except a.APIStatusError as exc:
            raise AIError(f"AI provider error (HTTP {exc.status_code}).") from exc
        except a.APIConnectionError as exc:
            raise AIError("Could not reach the AI provider.") from exc
        if resp.stop_reason == "refusal":
            raise AIError("The AI model declined to produce this suggestion.")
        if resp.stop_reason == "max_tokens":
            raise AIError("The AI response was cut off before it was complete.")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if not text:
            raise AIError("The AI provider returned no content.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIError("The AI provider returned malformed JSON.") from exc
        if not isinstance(data, dict):
            raise AIError("The AI provider returned JSON that is not an object.")
        usage = getattr(resp, "usage", None)
        return AIResult(data=data, model=getattr(resp, "model", self.model) or self.model,
                        input_tokens=getattr(usage, "input_tokens", 0) or 0,
                        output_tokens=getattr(usage, "output_tokens", 0) or 0)


class MockProvider:
    """Deterministic offline provider. Output is clearly labelled and only for tests/demos."""

    name = "mock"
    model = "mock"

    def __init__(self) -> None:
        if get_settings().is_production:
            raise AINotConfigured("The mock AI provider is disabled in production.")
        self.override: dict | None = None  # tests can inject raw outputs

    def generate(self, *, task: str, system: str, user: str, schema: dict) -> AIResult:
        if self.override is not None:
            return AIResult(data=self.override, model="mock")
        ctx = _extract_context(user)
        title = ctx.get("h1") or ctx.get("title") or "Page"
        data: dict[str, Any]
        if task == "meta_title":
            site_title = ctx.get("title") or ""
            combined = f"{title} – {site_title}" if site_title and site_title != title else f"{title} – overview"
            data = {"title": combined[:60], "rationale": "Mock: combines the page heading and title."}
        elif task == "meta_description":
            first = (ctx.get("first_paragraph") or title)[:150]
            data = {"description": first, "rationale": "Mock: based on the first paragraph."}
        elif task == "h1":
            data = {"h1": title[:70], "rationale": "Mock: based on the title."}
        elif task == "image_alt":
            data = {"alt": "Image related to " + title[:60], "rationale": "Mock alt text.", "is_decorative": False}
        elif task == "answer_paragraph":
            q = ctx.get("question") or "this question"
            data = {"answer_html": f"<p>{(ctx.get('first_paragraph') or 'See below.')[:240]}</p>",
                    "rationale": f"Mock answer for: {q}"}
        elif task == "faq_section":
            data = {"items": [{"question": f"What is {title}?", "answer": (ctx.get("first_paragraph") or title)[:300]}],
                    "rationale": "Mock FAQ from page content."}
        elif task == "json_ld":
            data = {"json_ld": json.dumps({"@context": "https://schema.org", "@type": "WebPage", "name": title}),
                    "rationale": "Mock WebPage markup."}
        elif task == "content_recommendations":
            data = {"recommendations": [{"heading": "Answer the main question first",
                                         "detail": "Start with a direct two-sentence summary.", "priority": "high"}],
                    "questions_to_answer": [f"What is {title}?"], "missing_topics": [], "entities": [],
                    "rationale": "Mock analysis."}
        elif task == "keyword_ideas":
            data = {"ideas": [{"keyword": f"{title.lower()} guide", "intent": "informational",
                               "reason": "Mock idea"}]}
        else:
            data = {}
        if task != "keyword_ideas" or "insufficient_information" in schema.get("properties", {}):
            data.setdefault("insufficient_information", False)
        return AIResult(data=data, model="mock")


def _extract_context(user: str) -> dict:
    """Mock helper: pull the trusted JSON context block out of the prompt."""
    start = user.find("<page_facts>")
    end = user.find("</page_facts>")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(user[start + len("<page_facts>"):end])
    except json.JSONDecodeError:
        return {}


_mock_singleton: MockProvider | None = None


def get_provider() -> AIProvider:
    global _mock_singleton
    s = get_settings()
    if s.ai_provider == "anthropic":
        return AnthropicProvider()
    if s.ai_provider == "mock":
        if _mock_singleton is None:
            _mock_singleton = MockProvider()
        return _mock_singleton
    raise AINotConfigured("No AI provider is configured (set AI_PROVIDER and the provider's API key).")


def ai_status() -> dict:
    s = get_settings()
    if s.ai_provider == "anthropic":
        return {"configured": bool(s.anthropic_api_key), "provider": "anthropic", "model": s.anthropic_model}
    if s.ai_provider == "mock":
        return {"configured": True, "provider": "mock", "model": "mock",
                "warning": "Mock AI provider: suggestions are placeholders for testing, not real AI output."}
    return {"configured": False, "provider": None, "model": None}
