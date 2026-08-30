from app.providers.base import ProviderNotConfiguredError
from app.providers.registry import ModelRole, get_claim_resolution_provider


class _FakeLLM:
    def __init__(self, role: ModelRole) -> None:
        self.role = role


def test_escalated_claim_resolution_falls_back_when_unconfigured(monkeypatch) -> None:
    calls: list[ModelRole] = []

    def provider(role: ModelRole):
        calls.append(role)
        if role == ModelRole.CLAIM_RESOLUTION_ESCALATED:
            raise ProviderNotConfiguredError("Falta claim_resolution_escalated")
        if role == ModelRole.CLAIM_RESOLUTION:
            return _FakeLLM(role)
        raise AssertionError(f"rol inesperado {role}")

    monkeypatch.setattr("app.providers.registry.get_structured_provider", provider)
    resolved = get_claim_resolution_provider(escalated=True)
    assert isinstance(resolved, _FakeLLM)
    assert resolved.role == ModelRole.CLAIM_RESOLUTION
    assert calls == [
        ModelRole.CLAIM_RESOLUTION_ESCALATED,
        ModelRole.CLAIM_RESOLUTION,
    ]


def test_base_claim_resolution_does_not_try_escalated(monkeypatch) -> None:
    calls: list[ModelRole] = []

    def provider(role: ModelRole):
        calls.append(role)
        return _FakeLLM(role)

    monkeypatch.setattr("app.providers.registry.get_structured_provider", provider)
    resolved = get_claim_resolution_provider(escalated=False)
    assert resolved.role == ModelRole.CLAIM_RESOLUTION
    assert calls == [ModelRole.CLAIM_RESOLUTION]


def test_escalated_claim_resolution_uses_escalated_when_configured(monkeypatch) -> None:
    def provider(role: ModelRole):
        return _FakeLLM(role)

    monkeypatch.setattr("app.providers.registry.get_structured_provider", provider)
    resolved = get_claim_resolution_provider(escalated=True)
    assert resolved.role == ModelRole.CLAIM_RESOLUTION_ESCALATED
