import time
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.io as pio
import requests
import streamlit as st
from sqlalchemy import create_engine, text

pio.renderers.default = "svg"


st.set_page_config(
    page_title="科技股與新聞情緒分析 Dashboard",
    page_icon="📈",
    layout="wide",
)


TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "TSLA"]


CREATE_STOCK_TABLE_SQL = """
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
"""


CREATE_NEWS_TABLE_SQL = """
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
"""


def get_database_url():
    url = st.secrets.get("DATABASE_URL", "")
    url = str(url).strip()

    if not url:
        st.error("尚未設定 DATABASE_URL。請到 Streamlit Cloud → Settings → Secrets 填入 Supabase connection string。")
        st.stop()

    return url


@st.cache_resource
def get_engine():
    return create_engine(get_database_url(), pool_pre_ping=True)


def initialize_tables(engine):
    with engine.begin() as conn:
        conn.execute(text(CREATE_STOCK_TABLE_SQL))
        conn.execute(text(CREATE_NEWS_TABLE_SQL))


def fetch_stock_from_yahoo(ticker):
    """
    Real cloud ETL source:
    Yahoo Finance chart API, executed on Streamlit Cloud.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

    params = {
        "range": "1y",
        "interval": "1d",
        "includePrePost": "false",
        "events": "div,splits",
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
    }

    response = requests.get(url, params=params, headers=headers, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(f"Yahoo Finance returned HTTP {response.status_code} for {ticker}: {response.text[:200]}")

    data = response.json()
    chart = data.get("chart", {})
    result = chart.get("result")
    error = chart.get("error")

    if error:
        raise RuntimeError(f"Yahoo Finance API error for {ticker}: {error}")

    if not result:
        raise RuntimeError(f"No chart result returned for {ticker}")

    result = result[0]
    timestamps = result.get("timestamp", [])
    quote = result.get("indicators", {}).get("quote", [{}])[0]

    if not timestamps or not quote:
        raise RuntimeError(f"No timestamp or quote data returned for {ticker}")

    df = pd.DataFrame({
        "date": [datetime.fromtimestamp(ts, tz=timezone.utc).date() for ts in timestamps],
        "ticker": ticker,
        "open": quote.get("open", []),
        "high": quote.get("high", []),
        "low": quote.get("low", []),
        "close": quote.get("close", []),
        "volume": quote.get("volume", []),
    })

    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_values("date")

    if df.empty:
        raise RuntimeError(f"Empty dataframe returned for {ticker}")

    df["daily_return"] = df["close"].pct_change()
    df["ma_7"] = df["close"].rolling(window=7).mean()
    df["ma_30"] = df["close"].rolling(window=30).mean()
    df["volatility_7"] = df["daily_return"].rolling(window=7).std()

    return df[
        [
            "ticker",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "daily_return",
            "ma_7",
            "ma_30",
            "volatility_7",
        ]
    ]


def extract_stock_data():
    frames = []
    logs = []

    for ticker in TICKERS:
        logs.append(f"Fetching {ticker} from Yahoo Finance chart API...")
        try:
            df = fetch_stock_from_yahoo(ticker)
            frames.append(df)
            logs.append(f"Fetched {len(df)} rows for {ticker}.")
        except Exception as exc:
            logs.append(f"Failed to fetch {ticker}: {exc}")

        time.sleep(1)

    if not frames:
        raise RuntimeError("No stock data was fetched from Yahoo Finance chart API.\n" + "\n".join(logs))

    result = pd.concat(frames, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"]).dt.date

    return result, logs


def score_sentiment(title):
    positive_words = [
        "support", "growth", "improves", "strong", "demand", "investment",
        "benefit", "surge", "gain", "optimism", "positive"
    ]
    negative_words = [
        "risk", "uncertainty", "pressure", "decline", "weak", "concern",
        "loss", "negative", "slowdown", "geopolitical"
    ]

    title_lower = title.lower()
    score = 0

    for word in positive_words:
        if word in title_lower:
            score += 0.25

    for word in negative_words:
        if word in title_lower:
            score -= 0.25

    score = max(min(score, 1), -1)

    if score > 0.1:
        sentiment = "Positive"
    elif score < -0.1:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"

    return sentiment, score


def fetch_market_news():
    """
    Tries to fetch news from Yahoo Finance search endpoint.
    If news endpoint fails, this function returns an empty DataFrame.
    The dashboard can still use the stock ETL successfully.
    """
    rows = []

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
    }

    for ticker in TICKERS:
        try:
            url = "https://query1.finance.yahoo.com/v1/finance/search"
            params = {
                "q": ticker,
                "quotesCount": 0,
                "newsCount": 5,
            }
            response = requests.get(url, params=params, headers=headers, timeout=20)

            if response.status_code != 200:
                continue

            data = response.json()
            news_items = data.get("news", [])

            for item in news_items:
                title = item.get("title", "")
                if not title:
                    continue

                provider = item.get("publisher", "Yahoo Finance")
                published = item.get("providerPublishTime")

                if published:
                    published_at = datetime.fromtimestamp(published, tz=timezone.utc)
                else:
                    published_at = datetime.now(timezone.utc)

                sentiment, sentiment_score = score_sentiment(title)

                rows.append({
                    "published_at": published_at,
                    "source": provider,
                    "title": title,
                    "sentiment": sentiment,
                    "sentiment_score": sentiment_score,
                    "related_event": f"{ticker} market news",
                    "possible_market_impact": f"News related to {ticker} may affect technology stock volatility and investor sentiment.",
                })

        except Exception:
            continue

        time.sleep(1)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["title"])
    return df


def upload_stock_data(engine, stock_df):
    temp_table = "stock_prices_upload_temp"

    stock_df.to_sql(temp_table, engine, if_exists="replace", index=False)

    upsert_sql = f"""
    INSERT INTO stock_prices
        (ticker, date, open, high, low, close, volume, daily_return, ma_7, ma_30, volatility_7)
    SELECT
        ticker, date, open, high, low, close, volume, daily_return, ma_7, ma_30, volatility_7
    FROM {temp_table}
    ON CONFLICT (ticker, date) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        daily_return = EXCLUDED.daily_return,
        ma_7 = EXCLUDED.ma_7,
        ma_30 = EXCLUDED.ma_30,
        volatility_7 = EXCLUDED.volatility_7;

    DROP TABLE IF EXISTS {temp_table};
    """

    with engine.begin() as conn:
        conn.execute(text(upsert_sql))


def upload_news_data(engine, news_df):
    if news_df.empty:
        return

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE news_sentiment RESTART IDENTITY;"))

    news_df.to_sql("news_sentiment", engine, if_exists="append", index=False)


def refresh_cloud_data():
    engine = get_engine()
    initialize_tables(engine)

    stock_df, logs = extract_stock_data()
    upload_stock_data(engine, stock_df)

    news_df = fetch_market_news()
    upload_news_data(engine, news_df)

    return {
        "stock_rows": len(stock_df),
        "news_rows": len(news_df),
        "logs": logs,
    }


@st.cache_data(ttl=600)
def load_stock_data():
    engine = get_engine()
    initialize_tables(engine)

    query = """
    SELECT
        ticker,
        date,
        open,
        high,
        low,
        close,
        volume,
        daily_return,
        ma_7,
        ma_30,
        volatility_7,
        created_at
    FROM stock_prices
    ORDER BY date ASC, ticker ASC;
    """

    df = pd.read_sql(query, engine)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])

    return df


@st.cache_data(ttl=600)
def load_news_data():
    engine = get_engine()
    initialize_tables(engine)

    query = """
    SELECT
        published_at,
        source,
        title,
        sentiment,
        sentiment_score,
        related_event,
        possible_market_impact
    FROM news_sentiment
    ORDER BY published_at DESC;
    """

    df = pd.read_sql(query, engine)
    if not df.empty:
        df["published_at"] = pd.to_datetime(df["published_at"]).dt.strftime("%Y-%m-%d %H:%M")

    return df


st.title("科技股與新聞情緒分析 Dashboard")
st.write("本版本會在 Streamlit Cloud 執行 ETL，從 Yahoo Finance API 抓取真實股價，寫入 Supabase，再從 Supabase 讀取資料視覺化。")

engine = get_engine()
initialize_tables(engine)

stock_df = load_stock_data()
news_df = load_news_data()

with st.sidebar:
    st.header("雲端資料庫控制")
    st.write("資料庫：Supabase / PostgreSQL")

    if st.button("執行雲端 ETL 並寫入 Supabase"):
        with st.spinner("正在從 Yahoo Finance API 抓取真實股價並寫入 Supabase..."):
            try:
                result = refresh_cloud_data()
                st.cache_data.clear()
                st.success(f"完成。股價資料寫入 {result['stock_rows']} 筆，新聞資料寫入 {result['news_rows']} 筆。")
                with st.expander("ETL logs"):
                    for line in result["logs"]:
                        st.write(line)
                st.rerun()
            except Exception as e:
                st.error("ETL 失敗。請查看錯誤訊息。")
                st.exception(e)

if stock_df.empty:
    st.warning("Supabase 目前沒有股價資料。請先按左側「執行雲端 ETL 並寫入 Supabase」。")
    st.stop()

st.success("目前已成功從 Supabase / PostgreSQL 讀取雲端資料。")

tab1, tab2, tab3, tab4 = st.tabs([
    "Dashboard 總覽",
    "股價走勢",
    "股票比較",
    "新聞與事件",
])

with tab1:
    latest_date = stock_df["date"].max()
    latest_df = stock_df[stock_df["date"] == latest_date]

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("追蹤股票數", stock_df["ticker"].nunique())

    with col2:
        st.metric("股價資料筆數", len(stock_df))

    with col3:
        st.metric("最新股價日期", latest_date.strftime("%Y-%m-%d"))

    with col4:
        avg_return = latest_df["daily_return"].mean() * 100
        st.metric("最新平均日報酬率", f"{avg_return:.2f}%")

    fig = px.line(
        stock_df,
        x="date",
        y="close",
        color="ticker",
        title="Stock Price Trend from Supabase Cloud Database",
    )
    st.plotly_chart(fig, use_container_width=True)

    if not news_df.empty:
        sentiment_summary = news_df.groupby("sentiment").size().reset_index(name="count")
        fig_sentiment = px.pie(
            sentiment_summary,
            names="sentiment",
            values="count",
            title="News Sentiment Distribution",
        )
        st.plotly_chart(fig_sentiment, use_container_width=True)

with tab2:
    tickers = sorted(stock_df["ticker"].unique())
    selected = st.multiselect("選擇股票", tickers, default=tickers)
    filtered = stock_df[stock_df["ticker"].isin(selected)]

    fig_price = px.line(
        filtered,
        x="date",
        y="close",
        color="ticker",
        title="Close Price Trend",
    )
    st.plotly_chart(fig_price, use_container_width=True)

    single = st.selectbox("選擇一檔股票查看移動平均與波動率", tickers)
    single_df = stock_df[stock_df["ticker"] == single].copy()

    ma_df = single_df[["date", "close", "ma_7", "ma_30"]].melt(
        id_vars="date",
        var_name="indicator",
        value_name="value",
    )

    fig_ma = px.line(
        ma_df,
        x="date",
        y="value",
        color="indicator",
        title=f"{single} Close Price and Moving Averages",
    )
    st.plotly_chart(fig_ma, use_container_width=True)

    fig_vol = px.line(
        single_df,
        x="date",
        y="volatility_7",
        title=f"{single} 7-Day Volatility",
    )
    st.plotly_chart(fig_vol, use_container_width=True)

    with st.expander("查看 Supabase 股價資料"):
        st.dataframe(filtered, use_container_width=True)

with tab3:
    summary = (
        stock_df.sort_values("date")
        .groupby("ticker")
        .agg(
            latest_close=("close", "last"),
            average_daily_return=("daily_return", "mean"),
            average_volatility=("volatility_7", "mean"),
            max_close=("close", "max"),
            min_close=("close", "min"),
        )
        .reset_index()
    )

    col1, col2 = st.columns(2)

    with col1:
        fig_close = px.bar(
            summary,
            x="ticker",
            y="latest_close",
            title="Latest Close Price",
        )
        st.plotly_chart(fig_close, use_container_width=True)

    with col2:
        fig_return = px.bar(
            summary,
            x="ticker",
            y="average_daily_return",
            title="Average Daily Return",
        )
        st.plotly_chart(fig_return, use_container_width=True)

    fig_vol = px.bar(
        summary,
        x="ticker",
        y="average_volatility",
        title="Average 7-Day Volatility",
    )
    st.plotly_chart(fig_vol, use_container_width=True)

    st.dataframe(summary, use_container_width=True)

with tab4:
    if news_df.empty:
        st.info("目前新聞資料表為空。股價資料已可正常展示；若 Yahoo News endpoint 被擋，新聞資料可能不會寫入。")
    else:
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("新聞資料筆數", len(news_df))

        with col2:
            st.metric("主要情緒", news_df["sentiment"].value_counts().idxmax())

        with col3:
            st.metric("平均情緒分數", f"{news_df['sentiment_score'].mean():.2f}")

        fig_score = px.bar(
            news_df,
            x="published_at",
            y="sentiment_score",
            color="sentiment",
            hover_data=["title", "source", "related_event"],
            title="News Sentiment Score by Date",
        )
        st.plotly_chart(fig_score, use_container_width=True)

        st.dataframe(news_df, use_container_width=True)

st.info("資料流程：Streamlit Cloud 執行 ETL → Yahoo Finance API → 資料清理與指標計算 → Supabase PostgreSQL → Dashboard 視覺化。")
