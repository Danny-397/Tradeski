# tracker/alerts.py
# Alert rules + alert engine for real-time stock monitoring.

import time
from dataclasses import dataclass
from typing import Callable, Optional, Dict


# Alert Rule Dataclass
@dataclass
class AlertRule:
    """A single alert rule with cooldown tracking."""
    name: str
    condition: Callable[[Dict], bool]
    message: str
    cooldown: int = 300
    last_triggered: Optional[float] = None


# Condition helpers
def volume_spike(multiplier: float = 2.0) -> Callable[[Dict], bool]:
    """Trigger when volume exceeds avg_volume * multiplier."""
    return lambda d: d.get("volume", 0) > d.get("avg_volume", 1) * multiplier


def volatility_spike(threshold: float = 2.5) -> Callable[[Dict], bool]:
    """Trigger when |zscore| exceeds threshold."""
    return lambda d: abs(d.get("zscore", 0)) > threshold


def volatility_regime() -> Callable[[Dict], str]:
    """Return volatility regime classification."""
    return lambda d: (
        "EXTREME" if abs(d.get("zscore", 0)) > 3.5
        else "HIGH" if abs(d.get("zscore", 0)) > 2.5
        else "NORMAL"
    )


def price_above(target: float) -> Callable[[Dict], bool]:
    return lambda d: d.get("price", 0) > target


def price_below(target: float) -> Callable[[Dict], bool]:
    return lambda d: d.get("price", 0) < target


def rsi_overbought() -> Callable[[Dict], bool]:
    return lambda d: d.get("rsi", 0) > 70


def rsi_oversold() -> Callable[[Dict], bool]:
    return lambda d: d.get("rsi", 0) < 30


def sma_cross_up() -> Callable[[Dict], bool]:
    """SMA crosses above EMA."""
    return lambda d: d.get("sma", 0) > d.get("ema", 0)


def sma_cross_down() -> Callable[[Dict], bool]:
    """SMA crosses below EMA."""
    return lambda d: d.get("sma", 0) < d.get("ema", 0)


# Alert Engine
class AlertEngine:
    """Evaluates alert rules and triggers notifications."""

    def __init__(self, notifier):
        self.notifier = notifier
        self.rules = []

    def add_rule(self, rule: AlertRule) -> None:
        """Register a new alert rule."""
        self.rules.append(rule)

    def evaluate(self, symbol: str, data: Dict) -> None:
        """Evaluate all rules against the latest data."""
        now = time.time()

        for rule in self.rules:
            # Cooldown check
            if rule.last_triggered and now - rule.last_triggered < rule.cooldown:
                continue

            # Condition check
            if rule.condition(data):
                self.notifier.alert(
                    symbol=symbol,
                    alert_type=rule.name,
                    title=f"{rule.name} Alert for {symbol}",
                    message=rule.message.format(**data),
                )
                rule.last_triggered = now


# Combined Power Signals
def combined_volume_volatility() -> AlertRule:
    """
    Hedge-fund style alert:
    Fires when BOTH volatility and volume spike.
    """
    return AlertRule(
        name="Volume + Volatility Spike",
        condition=lambda d: (
            abs(d.get("zscore", 0)) > 2.5
            and d.get("volume", 0) > d.get("avg_volume", 1) * 2
        ),
        message="High volatility + volume spike detected!",
        cooldown=600,
    )


def extreme_volatility() -> AlertRule:
    """Extreme volatility alert."""
    return AlertRule(
        name="Extreme Volatility",
        condition=lambda d: abs(d.get("zscore", 0)) > 3.5,
        message="EXTREME volatility detected! Z-score: {zscore}",
        cooldown=600,
    )
