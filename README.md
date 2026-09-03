# LogCouncil

LogCouncil 是一個 evidence-first 的多-Agent log 分析工具。它會讓不同角色分別檢查異常模式、事件時間線、跨服務關聯與可能根因，再由 Reviewer 尋找反證，最後產生可追溯至原始事件的分析報告。

目前專案處於 MVP 建置階段。核心分析預設在本機執行，不需要 API key。

產品承諾、證據邊界與 MVP 驗收條件記錄在 [`docs/PRODUCT_CONTRACT.md`](docs/PRODUCT_CONTRACT.md)。

## 開發環境

- Python 3.12
- Streamlit 1.x
- pytest 9.x

使用 Conda 建立並啟用環境：

```powershell
conda env create -f environment.local.yml
conda activate log-council
```

若環境已存在，可直接安裝或更新專案：

```powershell
python -m pip install -e ".[datasets,dev,ui]"
```

## 測試

```powershell
python -m pytest
```

## 使用 CLI 分析 Log

在終端顯示分析摘要：

```powershell
log-council analyze .\incident.log
```

同時輸出 deterministic、已遮蔽常見秘密的 JSON 報告：

```powershell
log-council analyze .\incident.log --output .\report.json
```

使用 `--json` 將 JSON 印到 stdout、`--omit-events` 縮小報告，或在確認後使用 `--force` 覆寫既有輸出。CLI 僅接受 UTF-8 的 `.log`、`.txt`、`.jsonl`，也可用 `-` 從 stdin 讀取。

## 啟動 Web UI

```powershell
streamlit run streamlit_app.py
```

瀏覽器介面可貼上或上傳 log，查看 Overview、Evidence、Agents、Handoffs 與 Data quality，並下載已遮蔽常見秘密的 JSON 報告。分析在本機執行，不需要 API key，也不會執行建議的操作。

部署至 Streamlit Community Cloud 時，請使用根目錄的 `streamlit_app.py` 與 Python 3.12。完整欄位與部署後檢查請參閱 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。

## 真實 Log 資料

目前整合 Loghub OpenStack 2k parser sample 與 RCAEval RE3-OB logs-only 根因案例。第三方原始資料不會提交至本 repository；來源、固定版本、checksum 與下載方式請參閱 [`data/README.md`](data/README.md)。

```powershell
python scripts/download_dataset.py loghub-openstack-2k
```

下載後執行測試，會額外逐行比對 LogCouncil 的解析結果與 Loghub 官方 structured reference。

## 目前支援的輸入

- 每行一個 JSON object 的 JSONL
- `timestamp level [service] message` 形式的一般文字 log
- 無法辨識的非空白行會保留為原始事件，並出現在資料品質問題中

MVP 僅分析 logs；metrics、distributed traces、packet captures 與 alarm-code event sequences 不在產品範圍內。

## 目前 Agent 流程

```text
Pattern Agent ──┐
Timeline Agent ─┼─> Root Cause Agent ─> Reviewer Agent ─> Consensus Report
Correlation Agent ─┘
```

所有 Agent 結論都必須引用事件 ID。第一版採 deterministic workflow，以便離線執行、測試與重播；後續再透過 provider adapter 接入 LLM。
