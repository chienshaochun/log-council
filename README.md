# LogCouncil

LogCouncil 是一個 evidence-first 的多-Agent log 分析工具。它會讓不同角色分別檢查異常模式、事件時間線與可能根因，再由 Reviewer 尋找反證，最後產生可追溯至原始事件的分析報告。

目前專案處於 MVP 建置階段。核心分析預設在本機執行，不需要 API key。

產品承諾、證據邊界與 MVP 驗收條件記錄在 [`docs/PRODUCT_CONTRACT.md`](docs/PRODUCT_CONTRACT.md)。

## 開發環境

- Python 3.12
- Streamlit 1.x
- pytest 9.x

使用 Conda 建立並啟用環境：

```powershell
conda env create -f environment.yml
conda activate log-council
```

若環境已存在，可直接安裝或更新專案：

```powershell
python -m pip install -e ".[dev,ui]"
```

## 測試

```powershell
python -m pytest
```

## 目前支援的輸入

- 每行一個 JSON object 的 JSONL
- `timestamp level [service] message` 形式的一般文字 log
- 無法辨識的非空白行會保留為原始事件，並出現在資料品質問題中

MVP 僅分析 logs；metrics、distributed traces、packet captures 與 alarm-code event sequences 不在產品範圍內。

## 預定 Agent 流程

```text
Pattern Agent ──┐
                ├─> Root Cause Agent ─> Reviewer Agent ─> Consensus Report
Timeline Agent ─┘
```

所有 Agent 結論都必須引用事件 ID。第一版採 deterministic workflow，以便離線執行、測試與重播；後續再透過 provider adapter 接入 LLM。
