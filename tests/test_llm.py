import json

import httpx

from app.config import Settings
from app.nlp.llm import LLMClient


def _ollama_transport(reply_fn):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.1:latest"}]})
        if request.url.path == "/api/chat":
            body = json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": reply_fn(body)}})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_ollama_detection_and_classification():
    def reply(body):
        assert body["format"] == "json"
        return json.dumps({"items": [
            {"id": "1", "category": "Performance Issue", "sentiment": -0.8, "summary": "slow"},
            {"id": "2", "category": "NOT A CATEGORY", "sentiment": 0.1},
            {"id": "99", "category": "Core Utility", "sentiment": 2},
        ]})
    llm = LLMClient(Settings(llm_provider="auto"), transport=_ollama_transport(reply))
    assert llm.provider == "ollama" and llm.enabled
    out = llm.classify_batch([("1", "it is slow"), ("2", "meh")])
    assert out == {"1": {"category": "Performance Issue", "sentiment": -0.8, "summary": "slow"}}


def test_malformed_json_is_tolerated():
    llm = LLMClient(Settings(llm_provider="ollama"), transport=_ollama_transport(lambda b: "not json at all"))
    assert llm.classify_batch([("1", "x")]) == {}
    assert llm.failures == 1


def test_fenced_json_cluster_naming():
    fenced = '```json\n{"name": "Slow reports", "summary": "s", "category": "Performance Issue", "business_impact": "b"}\n```'
    llm = LLMClient(Settings(llm_provider="ollama"), transport=_ollama_transport(lambda b: fenced))
    assert llm.name_cluster(["slow"], ["q"])["name"] == "Slow reports"


def test_fallback_to_heuristic_when_unreachable():
    def down(request):
        raise httpx.ConnectError("down")
    llm = LLMClient(Settings(llm_provider="auto", openai_api_key=""), transport=httpx.MockTransport(down))
    assert llm.provider == "heuristic" and not llm.enabled


def test_mining_with_mocked_llm(dataset):
    """End-to-end: LLM labels a sample, rest is propagated."""
    from app.mining import mine_feedback
    from app.nlp.classify import classify_text

    def reply(body):
        user = body["messages"][1]["content"]
        if "Feedback items" in user:
            items = [json.loads(line) for line in user.splitlines()[1:] if line.startswith("{")]
            return json.dumps({"items": [{"id": it["id"], "category": classify_text(it["text"])[0],
                                          "sentiment": 0.0, "summary": "ok"} for it in items]})
        return json.dumps({"name": "Theme", "summary": "s", "category": "UX Friction", "business_impact": "b"})

    s = Settings(llm_provider="ollama", llm_ticket_budget=60, llm_batch_size=20)
    llm = LLMClient(s, transport=_ollama_transport(reply))
    res = mine_feedback(dataset, llm, s, seed=7)
    src = res.meta["label_sources"]
    assert src.get("llm", 0) > 30 and src.get("propagated", 0) > 500
    assert res.meta["llm_heuristic_agreement"] == 1.0
    assert all(c["label_source"] == "llm" for c in res.clusters)
