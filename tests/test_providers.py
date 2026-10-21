import json
import subprocess
from unittest.mock import Mock

import httpx
import pytest

from rundown.providers import ClaudeProvider, OllamaProvider, ProviderFailure

DIGEST = {"overview":"Update", "key_updates":[], "action_items":[], "decisions":[], "priority_items":[]}


def test_ollama_schema_and_output(config):
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200,json={"models":[{"name":"test:latest"}]})
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["format"]["type"] == "object"
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(200,json={"message":{"content":json.dumps(DIGEST)}})
    provider=OllamaProvider(config,httpx.Client(base_url="http://localhost/",transport=httpx.MockTransport(handler)))
    provider.check()
    assert provider.generate("test").overview == "Update"


@pytest.mark.parametrize("payload", [{"message":{"content":"garbage"}}, {"message":{"content":"{}"}}, {}])
def test_ollama_bad_output(config,payload):
    client=httpx.Client(base_url="http://localhost/",transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload)))
    with pytest.raises(ProviderFailure,match="invalid digest"):
        OllamaProvider(config,client).generate("test")


def test_ollama_missing_model_and_unreachable(config):
    client=httpx.Client(base_url="http://localhost/",transport=httpx.MockTransport(lambda r:httpx.Response(200,json={"models":[]})))
    with pytest.raises(ProviderFailure,match="not installed"):
        OllamaProvider(config,client).check()
    client=httpx.Client(base_url="http://localhost/",transport=httpx.MockTransport(lambda r:httpx.Response(500)))
    with pytest.raises(ProviderFailure,match="Cannot reach"):
        OllamaProvider(config,client).check()


def test_claude_success_isolated_no_tools(config,monkeypatch):
    monkeypatch.setattr("shutil.which",lambda x:"/bin/claude")
    runner=Mock(side_effect=[subprocess.CompletedProcess([],0,"2.1.300",""), subprocess.CompletedProcess([],0,'{"loggedIn":true,"authMethod":"claude.ai"}',""), subprocess.CompletedProcess([],0,json.dumps({"structured_output":DIGEST}),"")])
    provider=ClaudeProvider(config,runner)
    provider.check()
    assert provider.generate("private Slack text").overview == "Update"
    args=runner.call_args.args[0]
    assert args[args.index("--tools")+1] == ""
    assert "--no-session-persistence" in args and "--safe-mode" in args
    assert "--bare" not in args  # bare mode would break subscription login
    assert "private Slack text" not in args
    assert runner.call_args.kwargs["input"] == "private Slack text"


@pytest.mark.parametrize("result", [FileNotFoundError(), subprocess.TimeoutExpired("claude",1), subprocess.CompletedProcess([],1,"","secret diagnostics"), subprocess.CompletedProcess([],0,"not JSON",""), subprocess.CompletedProcess([],0,'{"is_error":true}',"")])
def test_claude_failures(config,result):
    runner=Mock(side_effect=result) if isinstance(result,Exception) else Mock(return_value=result)
    with pytest.raises(ProviderFailure) as exc:
        ClaudeProvider(config,runner).generate("test")
    assert "secret diagnostics" not in str(exc.value)


def test_claude_missing_or_unauthenticated(config,monkeypatch):
    monkeypatch.setattr("shutil.which",lambda x:None)
    with pytest.raises(ProviderFailure,match="not found"):
        ClaudeProvider(config).check()
    monkeypatch.setattr("shutil.which",lambda x:"/bin/claude")
    runner=Mock(side_effect=[subprocess.CompletedProcess([],0,"version",""),subprocess.CompletedProcess([],0,'{"loggedIn":false}',"")])
    with pytest.raises(ProviderFailure,match="not authenticated"):
        ClaudeProvider(config,runner).check()

