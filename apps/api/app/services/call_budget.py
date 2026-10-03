"""Reserva de gasto antes de una llamada paga. Sin tope configurado no interviene."""

from __future__ import annotations

from contextvars import ContextVar
from decimal import Decimal

from app.core.config import get_settings


class CallBudgetExceeded(RuntimeError):
    """El presupuesto estimado no alcanza. No se hizo la llamada."""


class CallBudget:
    def __init__(self, cap: Decimal) -> None:
        self.cap = cap
        self.spent = Decimal("0")
        self.held = Decimal("0")

    def reserve(self, estimate: Decimal) -> Decimal:
        amount = max(Decimal("0"), estimate)
        if self.spent + self.held + amount > self.cap:
            raise CallBudgetExceeded(
                f"presupuesto {self.cap} insuficiente: gastado {self.spent} reservado {self.held} pedido {amount}"
            )
        self.held += amount
        return amount

    def settle(self, hold: Decimal, actual: Decimal) -> None:
        self.held = max(Decimal("0"), self.held - hold)
        self.spent += max(Decimal("0"), actual)

    def release(self, hold: Decimal) -> None:
        self.held = max(Decimal("0"), self.held - hold)


_BUDGET: ContextVar[CallBudget | None] = ContextVar("call_budget", default=None)


def install_budget(cap: Decimal) -> CallBudget:
    budget = CallBudget(cap)
    _BUDGET.set(budget)
    return budget


def active_budget() -> CallBudget | None:
    current = _BUDGET.get()
    if current is not None:
        return current
    settings = get_settings()
    if settings.cost_call_budget_usd is None:
        return None
    budget = CallBudget(Decimal(str(settings.cost_call_budget_usd)))
    _BUDGET.set(budget)
    return budget


def clear_budget() -> None:
    _BUDGET.set(None)
