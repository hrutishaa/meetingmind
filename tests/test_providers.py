import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from meetingmind.llm import extract_with_llm
from meetingmind.providers import OpenAICompatible, ProviderError, from_env
from meetingmind.transcript import parse_transcript

U = parse_transcript("Ann: I'll send the report by Friday.\nBo: Sounds good.")
GOOD = json.dumps([{"owner": "Ann", "task": "Send the report", "due": "friday",
                    "evidence": "I'll send the report by Friday."}])


@pytest.fixture
def server():
    """Fake OpenAI-compatible server. Set `script` to a list of (status, body) replies."""
    state = {"script": [], "requests": []}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            status, payload = state["script"].pop(0)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{srv.server_port}/v1"
    yield state
    srv.shutdown()


def reply(text):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}}]}


def provider(url, **kw):
    return OpenAICompatible(base_url=url, model="test-model", api_key="sk-secret", sleep=lambda s: None, **kw)


def test_sends_chat_completion_with_bearer_key(server):
    server["script"] = [reply("hello")]
    assert provider(server["url"])("prompt text") == "hello"
    req = server["requests"][0]
    assert req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer sk-secret"
    assert req["body"]["model"] == "test-model" and req["body"]["temperature"] == 0
    assert req["body"]["messages"][-1] == {"role": "user", "content": "prompt text"}


def test_retries_rate_limit_and_server_errors(server):
    server["script"] = [(429, {}), (503, {}), reply("ok")]
    p = provider(server["url"])
    assert p("x") == "ok" and p.calls == 3


def test_gives_up_without_leaking_key(server):
    server["script"] = [(500, {})] * 3
    p = provider(server["url"], max_retries=2)
    with pytest.raises(ProviderError) as e:
        p("x")
    assert "3 attempts" in str(e.value) and "sk-secret" not in str(e.value)
    assert "sk-secret" not in repr(p)


def test_client_errors_are_not_retried(server):
    server["script"] = [(401, {"error": "bad key"})]
    p = provider(server["url"])
    with pytest.raises(ProviderError, match="HTTP 401"):
        p("x")
    assert p.calls == 1


def test_unexpected_shape_raises(server):
    server["script"] = [(200, {"oops": True})]
    with pytest.raises(ProviderError, match="unexpected response"):
        provider(server["url"])("x")


def test_end_to_end_grounded_llm_items(server):
    server["script"] = [reply("Here you go:\n" + GOOD)]
    items, notes = extract_with_llm(U, provider(server["url"]))
    assert notes == [] and items[0].owner == "Ann" and items[0].due == "friday"


def test_provider_outage_falls_back_to_rules(server):
    server["script"] = [(401, {})]
    items, notes = extract_with_llm(U, provider(server["url"]))
    assert items[0].task == "Send the report" and "ProviderError" in notes[0]


def test_from_env():
    assert from_env({}) is None
    p = from_env({"MEETINGMIND_LLM_API_KEY": "k"})
    assert p.base_url == "https://api.openai.com/v1" and p.model == "gpt-4o-mini" and p.api_key == "k"
    local = from_env({"MEETINGMIND_LLM_BASE_URL": "http://localhost:11434/v1", "MEETINGMIND_LLM_MODEL": "llama3.1"})
    assert local.api_key == "" and local.model == "llama3.1"
