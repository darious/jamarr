from types import SimpleNamespace

from app.services.renderer.orchestrator import RendererOrchestrator


def _orchestrator(proxy_url):
    manager = SimpleNamespace(local_ip="192.0.2.10", renderer_base_url=proxy_url)
    registry = SimpleNamespace(backends={"upnp": SimpleNamespace(manager=manager)})
    return RendererOrchestrator(registry=registry)


def test_upnp_streams_go_through_renderer_proxy(monkeypatch):
    monkeypatch.delenv("HOST_PORT", raising=False)
    orchestrator = _orchestrator("http://192.0.2.10:8112")

    assert orchestrator._stream_base_url("upnp", None) == "http://192.0.2.10:8112"
    # Cast receivers do not need header recasing; they keep the API port.
    assert orchestrator._stream_base_url("cast", None) == "http://192.0.2.10:8111"


def test_upnp_stream_base_falls_back_without_proxy_url(monkeypatch):
    monkeypatch.delenv("HOST_PORT", raising=False)
    orchestrator = _orchestrator(None)

    assert orchestrator._stream_base_url("upnp", None) == "http://192.0.2.10:8111"
