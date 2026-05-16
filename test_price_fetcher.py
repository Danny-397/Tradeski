from tracker.price_fetcher import get_stock_price


def test_get_stock_price_valid_symbol():
    price = get_stock_price("AAPL")
    assert price is None or price > 0
