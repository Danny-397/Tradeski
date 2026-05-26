"""NewsAPI client with VADER sentiment scoring."""

import datetime
import requests
from typing import Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

NEWS_BASE = "https://newsapi.org/v2/everything"

# More descriptive queries produce better headline results than bare tickers
_COMPANY_QUERIES: dict[str, str] = {
    "AAPL":  "Apple stock",
    "MSFT":  "Microsoft stock",
    "NVDA":  "NVIDIA stock",
    "TSLA":  "Tesla stock",
    "AMZN":  "Amazon stock",
    "GOOGL": "Google Alphabet stock",
    "META":  "Meta stock",
    "SPY":   "S&P 500 market",
    "QQQ":   "Nasdaq tech market",
}

_vader = SentimentIntensityAnalyzer()

# Augment VADER's general-purpose lexicon with financial jargon.
# Without this, phrases like "beats expectations" or "record high" score 0.0.
_vader.lexicon.update({
    "beats": 2.0,       "beat": 2.0,        "exceeded": 1.8,   "exceeds": 1.8,
    "outperforms": 2.0, "outperform": 2.0,  "smashes": 1.5,    "surpasses": 1.8,
    "surge": 1.5,       "surges": 1.5,      "surging": 1.5,    "soars": 1.8,
    "rally": 1.5,       "rallies": 1.5,     "upgrade": 1.8,    "upgraded": 1.8,
    "bullish": 1.8,     "record high": 2.0, "all-time high": 2.2,
    "buyback": 1.2,     "dividend": 0.8,    "profit": 1.0,     "growth": 0.8,
    "misses": -2.0,     "miss": -2.0,       "missed": -2.0,    "disappoints": -2.0,
    "disappointing": -2.0, "slump": -1.5,   "slumps": -1.5,    "plunges": -2.0,
    "crash": -2.2,      "crashes": -2.2,    "recession": -2.0, "layoffs": -1.5,
    "bankruptcy": -3.0, "downgrade": -1.8,  "downgraded": -1.8,
    "investigation": -1.2, "lawsuit": -1.0, "tariff": -1.0,   "tariffs": -1.2,
    "inflation": -0.8,  "default": -2.0,    "loss": -1.5,      "losses": -1.5,
})


def _sentiment_score(text: str) -> float:
    """Return VADER compound score for a text string. Range: [-1, +1]."""
    return _vader.polarity_scores(text)["compound"]


def _label(score: float) -> str:
    if score > 0.05:
        return "bullish"
    if score < -0.05:
        return "bearish"
    return "neutral"


def _query_for(symbol: str) -> str:
    return _COMPANY_QUERIES.get(symbol.upper(), f"{symbol} stock")


def fetch_news(symbol: str, api_key: str, page_size: int = 10) -> list:
    """
    Fetch recent headlines for a symbol and score each with VADER sentiment.

    Returns a list of dicts:
        title, url, source, published_at, sentiment (float), sentiment_label (str)
    Returns [] on any API failure.
    """
    try:
        resp = requests.get(
            NEWS_BASE,
            params={
                "q":        _query_for(symbol),
                "apiKey":   api_key,
                "language": "en",
                "sortBy":   "publishedAt",
                "pageSize": page_size,
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw_articles = resp.json().get("articles", [])
    except Exception:
        return []

    result = []
    for a in raw_articles:
        title = (a.get("title") or "").strip()
        if not title or title == "[Removed]":
            continue

        desc  = (a.get("description") or "").strip()
        text  = f"{title}. {desc}" if desc else title
        score = _sentiment_score(text)

        result.append({
            "title":           title,
            "url":             a.get("url", ""),
            "source":          (a.get("source") or {}).get("name", "Unknown"),
            "published_at":    a.get("publishedAt", ""),
            "sentiment":       round(score, 3),
            "sentiment_label": _label(score),
        })

    return result


def aggregate_sentiment(articles: list) -> dict:
    """Compute aggregate sentiment stats from a scored article list."""
    if not articles:
        return {
            "score": 0.0, "label": "neutral", "count": 0,
            "bullish_count": 0, "neutral_count": 0, "bearish_count": 0,
        }

    scores = [a["sentiment"] for a in articles]
    avg    = sum(scores) / len(scores)

    return {
        "score":         round(avg, 3),
        "label":         _label(avg),
        "count":         len(articles),
        "bullish_count": sum(1 for s in scores if s > 0.05),
        "neutral_count": sum(1 for s in scores if -0.05 <= s <= 0.05),
        "bearish_count": sum(1 for s in scores if s < -0.05),
    }


def format_news_context(symbol: str, articles: list, agg: Optional[dict] = None) -> str:
    """Format scored articles into a concise text block for Ski's context."""
    if not articles:
        return ""

    if agg is None:
        agg = aggregate_sentiment(articles)

    label_map = {"bullish": "BULLISH", "bearish": "BEARISH", "neutral": "NEUTRAL"}
    sign      = "+" if agg["score"] >= 0 else ""

    lines = [
        f"RECENT NEWS SENTIMENT for {symbol} — {datetime.date.today()}:",
        f"  Aggregate: {label_map[agg['label']]} "
        f"(score: {sign}{agg['score']:.3f}, n={agg['count']})",
        f"  {agg['bullish_count']} bullish / "
        f"{agg['neutral_count']} neutral / "
        f"{agg['bearish_count']} bearish",
        "  Top headlines:",
    ]

    arrow = {"bullish": "↑", "bearish": "↓", "neutral": "→"}
    for a in articles[:6]:
        s = a["sentiment"]
        lines.append(
            f"    [{arrow[a['sentiment_label']]} {s:+.2f}] {a['title']}"
        )

    return "\n".join(lines)
