"""Tests for tracker/news.py — NewsAPI client and VADER sentiment scoring."""

from unittest.mock import patch, MagicMock

from tracker.news import (
    fetch_news,
    aggregate_sentiment,
    format_news_context,
    _sentiment_score,
    _label,
)


# ---------------------------------------------------------------------------
# Sentiment helpers
# ---------------------------------------------------------------------------

def test_label_bullish():
    assert _label(0.5) == "bullish"
    assert _label(0.06) == "bullish"


def test_label_bearish():
    assert _label(-0.5) == "bearish"
    assert _label(-0.06) == "bearish"


def test_label_neutral():
    assert _label(0.0) == "neutral"
    assert _label(0.04) == "neutral"
    assert _label(-0.04) == "neutral"


def test_financial_lexicon_augmentation():
    """Financial jargon should score non-zero after lexicon augmentation."""
    score = _sentiment_score("Apple beats expectations, stock surges to record high")
    assert score > 0.2, f"Expected positive score, got {score}"

    score = _sentiment_score("Company misses earnings, stock crashes on bankruptcy fears")
    assert score < -0.2, f"Expected negative score, got {score}"


# ---------------------------------------------------------------------------
# fetch_news — mocked HTTP
# ---------------------------------------------------------------------------

_FAKE_ARTICLES = [
    {
        "title": "Apple beats Q4 earnings expectations",
        "description": "Revenue surged 8% year-over-year.",
        "url": "https://example.com/1",
        "source": {"name": "Reuters"},
        "publishedAt": "2024-11-01T12:00:00Z",
    },
    {
        "title": "Apple faces lawsuit over patent dispute",
        "description": "Analysts downgraded the stock.",
        "url": "https://example.com/2",
        "source": {"name": "Bloomberg"},
        "publishedAt": "2024-11-01T10:00:00Z",
    },
    {
        "title": "[Removed]",
        "description": "",
        "url": "",
        "source": {"name": "Unknown"},
        "publishedAt": "",
    },
]


def _mock_response(articles):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"articles": articles}
    return mock


@patch("tracker.news.requests.get")
def test_fetch_news_returns_scored_articles(mock_get):
    mock_get.return_value = _mock_response(_FAKE_ARTICLES)
    result = fetch_news("AAPL", api_key="test-key")

    # [Removed] article should be filtered out
    assert len(result) == 2
    for a in result:
        assert "title" in a
        assert "sentiment" in a
        assert "sentiment_label" in a
        assert a["sentiment_label"] in ("bullish", "bearish", "neutral")


@patch("tracker.news.requests.get")
def test_fetch_news_filters_removed_titles(mock_get):
    mock_get.return_value = _mock_response(_FAKE_ARTICLES)
    result = fetch_news("AAPL", api_key="test-key")
    titles = [a["title"] for a in result]
    assert "[Removed]" not in titles


@patch("tracker.news.requests.get")
def test_fetch_news_returns_empty_on_http_error(mock_get):
    mock_get.side_effect = Exception("Network error")
    result = fetch_news("AAPL", api_key="test-key")
    assert result == []


@patch("tracker.news.requests.get")
def test_fetch_news_uses_company_query(mock_get):
    mock_get.return_value = _mock_response([])
    fetch_news("AAPL", api_key="test-key")
    params = mock_get.call_args_list[0][1]["params"]
    assert "Apple" in params["q"]
    assert params["searchIn"] == "title"                 # not anywhere in the article body
    assert "reuters.com" in params["domains"]            # finance sites first


def test_query_uses_the_company_name_for_any_ticker():
    from tracker.news import _query_for, short_name
    assert _query_for("AAPL") == "Apple OR AAPL"
    assert _query_for("ADM") == '"Archer Daniels Midland" OR ADM'      # from the search index
    assert _query_for("SPY") == '"S&P 500" OR "stock market" OR "Wall Street" OR SPY'
    assert _query_for("A") == "Agilent"                              # a one-letter ticker is a word
    assert _query_for("ZZZQX") == "ZZZQX"                               # unknown: the ticker alone
    assert short_name("Apple Inc.") == "Apple"
    assert short_name("Arch Capital Group") == "Arch Capital"
    assert short_name("Berkshire Hathaway Inc. Class B") == "Berkshire Hathaway"
    assert short_name("SoFi Technologies") == "SoFi"
    assert short_name("Lilly (Eli)") == "Eli Lilly"
    assert _query_for("F") == "Ford"


@patch("tracker.news.requests.get")
def test_few_finance_results_widen_the_search_and_dedupe(mock_get):
    one = _FAKE_ARTICLES[:1]
    mock_get.side_effect = [_mock_response(one), _mock_response(_FAKE_ARTICLES)]
    result = fetch_news("AAPL", api_key="test-key")
    first, second = (c[1]["params"] for c in mock_get.call_args_list)
    assert "domains" in first and "domains" not in second
    assert second["searchIn"] == "title"
    assert [a["title"] for a in result] == ["Apple beats Q4 earnings expectations",
                                            "Apple faces lawsuit over patent dispute"]


@patch("tracker.news.requests.get")
def test_enough_finance_results_need_one_request(mock_get):
    many = [{**_FAKE_ARTICLES[0], "title": f"Apple headline {i}"} for i in range(6)]
    mock_get.return_value = _mock_response(many)
    assert len(fetch_news("AAPL", api_key="test-key", page_size=5)) == 5
    assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# aggregate_sentiment
# ---------------------------------------------------------------------------

def test_aggregate_empty():
    agg = aggregate_sentiment([])
    assert agg["score"] == 0.0
    assert agg["label"] == "neutral"
    assert agg["count"] == 0


def test_aggregate_counts():
    articles = [
        {"sentiment": 0.5,  "sentiment_label": "bullish"},
        {"sentiment": -0.3, "sentiment_label": "bearish"},
        {"sentiment": 0.0,  "sentiment_label": "neutral"},
    ]
    agg = aggregate_sentiment(articles)
    assert agg["count"] == 3
    assert agg["bullish_count"] == 1
    assert agg["bearish_count"] == 1
    assert agg["neutral_count"] == 1


# ---------------------------------------------------------------------------
# format_news_context
# ---------------------------------------------------------------------------

def test_format_news_context_empty():
    assert format_news_context("AAPL", []) == ""


@patch("tracker.news.requests.get")
def test_format_news_context_structure(mock_get):
    mock_get.return_value = _mock_response(_FAKE_ARTICLES)
    articles = fetch_news("AAPL", api_key="test-key")
    text = format_news_context("AAPL", articles)
    assert "AAPL" in text
    assert "Aggregate" in text
    assert "bullish" in text.lower() or "bearish" in text.lower() or "neutral" in text.lower()
