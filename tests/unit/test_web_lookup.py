import json

import httpx
import pytest

from app.providers import web
from app.providers.base import Completion
from app.security.secret_store import MemorySecretBackend, SecretStore
from app.store.settings import Settings

pytestmark = pytest.mark.anyio


class FakeHub:
    def __init__(self, handler, key="tf_test"):
        self.secrets = SecretStore(MemorySecretBackend())
        if key:
            self.secrets.set("tinyfish", key)
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.prompts = []

    def settings(self):
        return Settings(cloud_consent=True)

    def provider(self, name):
        return None

    async def complete(self, system, user, json_mode=False):
        self.prompts.append(user)
        return Completion(text="1. Select the clip.\n2. Adjust > Basic > Brightness.", provider="mock", model="m",
                          latency_ms=1)


async def test_search_then_read_pages_then_steps():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.host, request.headers.get("x-api-key")))
        if request.url.host == "api.search.tinyfish.ai":
            assert request.url.params["query"] == "CapCut desktop adjust brightness"
            return httpx.Response(200, json={"results": [
                {"url": "https://a.example/capcut", "title": "A", "snippet": "a"},
                {"url": "https://b.example/capcut", "title": "B", "snippet": "b"}]})
        body = json.loads(request.content)
        assert body["urls"] == ["https://a.example/capcut", "https://b.example/capcut"]
        return httpx.Response(200, json={"results": [{"url": "https://a.example/capcut", "text": "Open Adjust tab " * 30}]})

    hub = FakeHub(handler)
    found = await web.look_up(hub, "CapCut desktop adjust brightness")
    assert "Brightness" in found["answer"] and found["via"] == "tinyfish"
    assert found["sources"] == ["https://a.example/capcut", "https://b.example/capcut"]
    assert seen == [("GET", "api.search.tinyfish.ai", "tf_test"), ("POST", "api.fetch.tinyfish.ai", "tf_test")]
    # the page that could not be read still contributes its snippet; page text is marked as data
    assert "Open Adjust tab" in hub.prompts[0] and "url=\"https://b.example/capcut\"" in hub.prompts[0]


async def test_without_a_key_it_searches_and_reads_by_itself(monkeypatch):
    async def engines(query, n):
        return [{"title": "Guide", "url": "https://guide.example/steps", "snippet": "s"},
                {"title": "Video", "url": "https://www.youtube.com/watch?v=x", "snippet": "v"}]

    monkeypatch.setattr(web, "keyless_search", engines)
    fetched = []

    def handler(request: httpx.Request):
        fetched.append(str(request.url))
        html = "<html><body><nav>menu</nav><article><h1>Steps</h1>" + "<p>Click Adjust then Brightness.</p>" * 20 +                "</article><script>evil()</script></body></html>"
        return httpx.Response(200, html=html)

    hub = FakeHub(handler, key=None)
    found = await web.look_up(hub, "CapCut brightness")
    assert found["via"] == "web" and found["pages_read"] == 1
    assert fetched == ["https://guide.example/steps"]  # video pages are not fetched
    assert "Click Adjust then Brightness." in hub.prompts[0] and "evil()" not in hub.prompts[0]


async def test_when_every_search_engine_fails_it_still_answers_and_says_so(monkeypatch):
    async def nothing(query, n):
        return []

    monkeypatch.setattr(web, "keyless_search", nothing)
    hub = FakeHub(lambda r: httpx.Response(500), key=None)
    found = await web.look_up(hub, "anything at all")
    assert found["via"] == "memory" and found["sources"] == []
