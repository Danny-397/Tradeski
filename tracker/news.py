"""NewsAPI client with VADER sentiment scoring."""

import datetime
import json
import os
import re
import requests
from functools import lru_cache
from typing import Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

NEWS_BASE = "https://newsapi.org/v2/everything"

# Headlines are searched in titles only, first on financial news sites. A
# full-text search for "Apple stock" sorted by date returned whatever mentioned
# Apple anywhere in the body: politics, app deals, history pieces.
FINANCE_DOMAINS = ",".join([
    "reuters.com", "bloomberg.com", "cnbc.com", "wsj.com", "marketwatch.com", "barrons.com",
    "ft.com", "finance.yahoo.com", "fool.com", "investors.com", "seekingalpha.com", "benzinga.com",
    "businessinsider.com", "forbes.com", "thestreet.com", "zacks.com", "investing.com", "nasdaq.com",
    "apnews.com", "axios.com", "fortune.com", "techcrunch.com", "theverge.com",
])
MIN_FINANCE_RESULTS = 4      # fewer than this from the finance sites, and the search widens

# Title terms for names the company list doesn't cover well (ETFs, Alphabet's two names).
_QUERY_TERMS: dict[str, list] = {
    "SPY":   ["S&P 500", "stock market", "Wall Street"],
    "QQQ":   ["Nasdaq", "tech stocks"],
    "DIA":   ["Dow Jones", "Dow"],
    "IWM":   ["Russell 2000", "small caps"],
    "GOOGL": ["Alphabet", "Google"],
    "GOOG":  ["Alphabet", "Google"],
    "META":  ["Meta Platforms", "Meta", "Facebook"],
    "BRK-B": ["Berkshire Hathaway", "Berkshire"],
    "F":     ["Ford"],
}

# Suffixes dropped from a company's legal name to get the name headlines use.
_SUFFIX = re.compile(
    r"[,.]?\s+(Inc\.?|Incorporated|Technologies|Corp\.?|Corporation|Co\.?|Company|plc|PLC|Ltd\.?|Limited|"
    r"Holdings?|Group|N\.V\.|S\.A\.|AG|SE|Class [A-C]|\(The\))$")

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


@lru_cache(maxsize=1)
def _company_names() -> dict:
    """Ticker -> company name, from the dashboard's own search index (frontend/symbols.js)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "symbols.js")
    try:
        text = open(path, encoding="utf-8").read()
        pairs = json.loads(re.search(r"=\s*(\[.*\]);", text, re.S).group(1))
        return {sym: name for sym, name in pairs}
    except (OSError, AttributeError, ValueError):
        return {}


def short_name(name: str) -> str:
    """ "Apple Inc." -> "Apple", "Arch Capital Group" -> "Arch Capital"."""
    inverted = re.fullmatch(r"(.+) \((.+)\)", name)       # "Lilly (Eli)" -> "Eli Lilly"
    if inverted:
        name = f"{inverted.group(2)} {inverted.group(1)}"
    prev = None
    while prev != name:
        prev, name = name, _SUFFIX.sub("", name).strip()
    return name


def _query_for(symbol: str) -> str:
    """A NewsAPI title query: the company's name(s), plus the ticker when it is
    long enough not to be an ordinary word ("ALL", "IT" and "ON" are tickers)."""
    sym = symbol.upper()
    terms = list(_QUERY_TERMS.get(sym) or [])
    if not terms:
        name = _company_names().get(sym)
        terms = [short_name(name)] if name else []
    if len(sym) >= 3 or not terms:
        terms.append(sym)
    return " OR ".join(f'"{t}"' if " " in t or "&" in t else t for t in dict.fromkeys(terms))


def _search(params: dict) -> list:
    resp = requests.get(NEWS_BASE, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json().get("articles", [])


def fetch_news(symbol: str, api_key: str, page_size: int = 10) -> list:
    """
    Fetch recent headlines for a symbol and score each with VADER sentiment.

    Returns a list of dicts:
        title, url, source, published_at, sentiment (float), sentiment_label (str)
    Returns [] on any API failure.
    """
    params = {
        "q":        _query_for(symbol),
        "searchIn": "title",
        "apiKey":   api_key,
        "language": "en",
        "sortBy":   "publishedAt",
        "pageSize": page_size,
    }
    raw_articles: list = []
    try:
        raw_articles = _search({**params, "domains": FINANCE_DOMAINS})
    except Exception:
        raw_articles = []
    if len(raw_articles) < MIN_FINANCE_RESULTS:
        # Smaller companies get little coverage on the big finance sites: widen
        # to any source, still matching the name in the title, and top up.
        try:
            raw_articles = raw_articles + _search(params)
        except Exception:
            pass
    if not raw_articles:
        return []

    result = []
    seen = set()
    for a in raw_articles:
        title = (a.get("title") or "").strip()
        if not title or title == "[Removed]" or title.lower() in seen:
            continue
        seen.add(title.lower())

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

    return result[:page_size]


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

    # Headlines first: the model reads a headline better than a word-list
    # score can, so the VADER numbers come last, labelled as a rough hint, and
    # can no longer anchor the answer.
    lines = [f"RECENT NEWS for {symbol} (as of {datetime.date.today()}), newest first:"]
    for a in articles[:6]:
        meta = ", ".join(
            x for x in (a.get("source"), (a.get("published_at") or "")[:10]) if x
        )
        lines.append(f"  - {a['title']}" + (f" ({meta})" if meta else ""))

    sign = "+" if agg["score"] >= 0 else ""
    lines.append(
        "  Automated headline sentiment (VADER word-list score; a rough hint only, "
        f"judge the headlines yourself): Aggregate {agg['label']} "
        f"({sign}{agg['score']:.3f}, n={agg['count']}; "
        f"{agg['bullish_count']} bullish / {agg['neutral_count']} neutral / "
        f"{agg['bearish_count']} bearish)"
    )

    return "\n".join(lines)
