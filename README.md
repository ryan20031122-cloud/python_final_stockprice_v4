# 科技股與新聞情緒分析 Dashboard

這是簡化後的雲端 ETL 版本。

## 主要設計

- 前端：Streamlit + Plotly
- 雲端資料庫：Supabase PostgreSQL
- ETL：由 Streamlit Cloud 執行
- 股價資料來源：Yahoo Finance chart API
- 資料處理：daily_return、ma_7、ma_30、volatility_7
- Dashboard 資料來源：Supabase PostgreSQL

## 使用方式

1. 將本專案部署到 Streamlit Cloud
2. 在 Streamlit Secrets 設定：

```toml
DATABASE_URL = "postgresql://postgres.xxxxx:你的密碼@aws-0-xxxxx.pooler.supabase.com:6543/postgres"
```

3. 打開 Streamlit URL
4. 點左側「執行雲端 ETL 並寫入 Supabase」
5. App 會抓取真實股價資料，寫入 Supabase，再從 Supabase 顯示 Dashboard

## 說明

本版本不使用 GitHub Actions，避免 workflow 設定造成錯誤。
資料不是手動測試資料，而是由 Streamlit Cloud 端執行 ETL 後寫入 Supabase。
