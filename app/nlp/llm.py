"""Intelligence layer: pluggable LLM client with structured-JSON prompting.

Providers
---------
- ``ollama``    Local model via Ollama (e.g. Llama 3.1) - fully offline.
- ``openai``    Any OpenAI-compatible Chat Completions endpoint (OpenAI, Groq,
                Together, vLLM, LM Studio ...) via OPENAI_BASE_URL.
- ``heuristic`` No LLM: deterministic lexicon + template fallbacks.

``auto`` probes Ollama first, then an OpenAI key, then falls back to heuristic.
Every LLM output is validated; anything malformed silently falls back to the
heuristic result for that item, so the pipeline never breaks.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from ..config import Settings
from .classify import CATEGORIES

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
CLASSIFY_SYSTEM = f"""You are a senior product analyst mining enterprise SaaS customer feedback.
Classify EACH feedback item into exactly one category:
- "Core Utility": the feature delivers value (praise, reliance, time saved, or requests to extend it).
- "UX Friction": usability pain - confusing navigation, too many steps, poor docs/onboarding, layout issues.
- "Performance Issue": speed, crashes, errors, timeouts, sync failures, reliability defects.
- "Feature Bloat Indicator": the feature is unused, irrelevant, redundant, cluttering, or customers want it removed/disabled.
Also score sentiment from -1.0 (very negative) to 1.0 (very positive) and write a 3-8 word summary.
Respond ONLY with JSON of the form:
{{"items": [{{"id": "<id>", "category": "<one of {CATEGORIES}>", "sentiment": <float>, "summary": "<text>"}}]}}"""

CLUSTER_SYSTEM = f"""You are a product strategy analyst. You are given a cluster of semantically similar
customer feedback (top keywords + representative quotes; feature names are masked as "this feature").
Name the underlying theme and assess it. Respond ONLY with JSON:
{{"name": "<2-5 word theme name>", "summary": "<one sentence describing the theme>",
 "category": "<one of {CATEGORIES}>",
 "business_impact": "<one sentence on the commercial / engineering-cost implication>"}}"""

MEMO_SYSTEM = """You are a strategy consultant writing a crisp executive memo for a SaaS company's CPO and CFO.
Use the provided portfolio analytics JSON only - do not invent numbers. Frame insights with the BCG matrix,
Product Lifecycle and strategic cost analysis. Format as Markdown with these sections:
## Headline (one sentence), ## Key findings (3-5 bullets), ## Recommended actions (3-5 bullets naming features),
## Risks & mitigations (2-3 bullets). Keep it under 300 words. Amounts are INR (use lakh / crore notation)."""


def _extract_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


class LLMClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._transport = transport
        self.provider, self.model = self._detect()
        self.calls = 0
        self.failures = 0

    # ------------------------------------------------------------------ setup
    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(timeout=timeout or self.settings.llm_timeout_s, transport=self._transport)

    def _ollama_ok(self) -> bool:
        try:
            with self._client(timeout=2.0) as c:
                r = c.get(f"{self.settings.ollama_host.rstrip('/')}/api/tags")
                r.raise_for_status()
                models = [m.get("name", "") for m in r.json().get("models", [])]
                want = self.settings.ollama_model
                return any(m == want or m.split(":")[0] == want.split(":")[0] for m in models)
        except Exception:  # noqa: BLE001
            return False

    def _detect(self) -> tuple[str, str]:
        p = self.settings.llm_provider
        if p == "heuristic":
            return "heuristic", "rules+lexicon"
        if p in ("auto", "ollama") and self._ollama_ok():
            return "ollama", self.settings.ollama_model
        if p == "ollama":
            log.warning("Ollama not reachable at %s or model missing; using heuristic.", self.settings.ollama_host)
        if p in ("auto", "openai") and self.settings.openai_api_key:
            return "openai", self.settings.openai_model
        return "heuristic", "rules+lexicon"

    @property
    def enabled(self) -> bool:
        return self.provider != "heuristic"

    def info(self) -> dict:
        return {"provider": self.provider, "model": self.model, "enabled": self.enabled,
                "calls": self.calls, "failures": self.failures}

    # ------------------------------------------------------------------ chat
    def chat(self, system: str, user: str, json_mode: bool = True) -> str | None:
        if not self.enabled:
            return None
        self.calls += 1
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            with self._client() as c:
                if self.provider == "ollama":
                    body = {"model": self.model, "messages": msgs, "stream": False,
                            "options": {"temperature": 0}}
                    if json_mode:
                        body["format"] = "json"
                    r = c.post(f"{self.settings.ollama_host.rstrip('/')}/api/chat", json=body)
                    r.raise_for_status()
                    return r.json()["message"]["content"]
                url = f"{self.settings.openai_base_url.rstrip('/')}/chat/completions"
                headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
                body = {"model": self.model, "messages": msgs, "temperature": 0}
                if json_mode:
                    body["response_format"] = {"type": "json_object"}
                r = c.post(url, json=body, headers=headers)
                if r.status_code == 400 and json_mode:  # endpoint without JSON mode support
                    body.pop("response_format")
                    r = c.post(url, json=body, headers=headers)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            self.failures += 1
            log.warning("LLM call failed (%s): %s", self.provider, exc)
            return None

    def chat_json(self, system: str, user: str) -> Any | None:
        raw = self.chat(system, user, json_mode=True)
        if raw is None:
            return None
        try:
            return _extract_json(raw)
        except Exception:  # noqa: BLE001
            self.failures += 1
            log.warning("LLM returned non-JSON output")
            return None

    # --------------------------------------------------------------- tasks
    def classify_batch(self, items: list[tuple[str, str]]) -> dict[str, dict]:
        """items: [(id, text)] -> {id: {category, sentiment, summary}} (only valid rows)."""
        payload = "\n".join(json.dumps({"id": i, "text": t[:600]}) for i, t in items)
        data = self.chat_json(CLASSIFY_SYSTEM, f"Feedback items (JSON lines):\n{payload}")
        out: dict[str, dict] = {}
        rows = data.get("items", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        valid_ids = {i for i, _ in items}
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid, cat = str(row.get("id", "")), row.get("category")
            if rid not in valid_ids or cat not in CATEGORIES:
                continue
            try:
                sent = max(-1.0, min(1.0, float(row.get("sentiment", 0))))
            except (TypeError, ValueError):
                sent = 0.0
            out[rid] = {"category": cat, "sentiment": sent, "summary": str(row.get("summary", ""))[:120]}
        return out

    def name_cluster(self, keywords: list[str], quotes: list[str]) -> dict | None:
        user = "Top keywords: " + ", ".join(keywords) + "\nRepresentative quotes:\n" + \
               "\n".join(f"- {q[:300]}" for q in quotes[:8])
        data = self.chat_json(CLUSTER_SYSTEM, user)
        if not isinstance(data, dict) or not data.get("name"):
            return None
        if data.get("category") not in CATEGORIES:
            data["category"] = None
        return {k: str(v)[:240] if v is not None else None for k, v in data.items()
                if k in ("name", "summary", "category", "business_impact")}

    def write_memo(self, context: dict) -> str | None:
        return self.chat(MEMO_SYSTEM, json.dumps(context, default=str), json_mode=False)
