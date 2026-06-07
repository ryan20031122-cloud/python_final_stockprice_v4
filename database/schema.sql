CREATE TABLE IF NOT EXISTS stock_prices (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    daily_return DOUBLE PRECISION,
    ma_7 DOUBLE PRECISION,
    ma_30 DOUBLE PRECISION,
    volatility_7 DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, date)
);

CREATE TABLE IF NOT EXISTS news_sentiment (
    id SERIAL PRIMARY KEY,
    published_at TIMESTAMP,
    source TEXT,
    title TEXT,
    sentiment TEXT,
    sentiment_score DOUBLE PRECISION,
    related_event TEXT,
    possible_market_impact TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
