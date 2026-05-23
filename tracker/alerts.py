import time
from dataclasses import dataclass
from typing import Callable, Optional

@dataclass
class AlertRule:
    name: str
    condition: Callable[[dict], bool]
    message: str
    cooldown: int = 300  # seconds between alerts
    last_triggered: Optional[float] = None

# Real alert engine 
# easily intergates with the exitsing PUSHOVER notifer
# This is how trading bots sturcutre alerts and is something that I can expand on. 

def volume_spike(multiplier=2.0):
    return lambda d: d.get("volume", 0) > (d.get("avg_volume", 1) * multiplier)

# triggers when volatility excceds a z score threshold 
def volatility_spike(threshold=2.5):
    return lambda d: abs(d.get("zscore", 0)) > threshold

def volatility_regime():
    return lambda d: (
        "EXTREME" if abs(d["zscore"]) > 3.5 else
        "HIGH" if abs(d["zscore"]) > 2.5 else
        "NORMAL"
    )
alert_engine.add_rule(AlertRule(
    name="Extreme Volatility",
    condition=lambda d: abs(d.get("zscore", 0)) > 3.5,
    message="EXTREME volatility detected! Z-score: {zscore}",
    cooldown=600
))
# Detects extreme volatility events 
# Gives a more nuanced alert system 
# This makes the backend sore of like a quant engine, which is good becasue I will be expanding on that.



# This is a power signal used by hedge funds 
alert_engine.add_rule(AlertRule(
    name="Volume + Volatility Spike",
    condition=lambda d: (
        abs(d.get("zscore", 0)) > 2.5 and
        d.get("volume", 0) > d.get("avg_volume", 1) * 2
    ),
    message="High volatility + volume spike detected!",
    cooldown=600
))
# When volume and volitlity spike together, it usally means: news, earnings leak, whale activity, institutional buying/selling, breakout or breakdon
# This is a valuable alert 


class AlertEngine:
    def __init__(self, notifier):
        self.notifier = notifier
        self.rules = []

    def add_rule(self, rule: AlertRule):
        self.rules.append(rule)

    def evaluate(self, symbol: str, data: dict):
        now = time.time()

        for rule in self.rules:
            if rule.last_triggered and now - rule.last_triggered < rule.cooldown:
                continue  # still cooling down

            if rule.condition(data):
                self.notifier.alert(
                    symbol=symbol,
                    alert_type=rule.name,
                    title=f"{rule.name} Alert for {symbol}",
                    message=rule.message.format(**data)
                )
                rule.last_triggered = now
  def price_above(target):
    return lambda d: d["price"] > target

def price_below(target):
    return lambda d: d["price"] < target

def rsi_overbought():
    return lambda d: d.get("rsi", 0) > 70

def rsi_oversold():
    return lambda d: d.get("rsi", 0) < 30

def sma_cross_up():
    return lambda d: d["sma"] > d["ema"]

def sma_cross_down():
    return lambda d: d["sma"] < d["ema"]

