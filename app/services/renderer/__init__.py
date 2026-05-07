def get_renderer_orchestrator():
    from app.services.renderer.orchestrator import get_renderer_orchestrator as factory

    return factory()


def get_renderer_registry():
    from app.services.renderer.registry import get_renderer_registry as factory

    return factory()

__all__ = ["get_renderer_orchestrator", "get_renderer_registry"]
