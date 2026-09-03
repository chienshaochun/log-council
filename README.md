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
streamlit run app.py
```

瀏覽器介面可貼上或上傳 log，查看 Overview、Evidence、Agents、Handoffs 與 Data quality，並下載已遮蔽常見秘密的 JSON 報告。分析在本機執行，不需要 API key，也不會執行建議的操作。

### 選用：本機 LLM 問答

若要在自己電腦上使用自然語言問答，先安裝並啟動 Ollama，再下載專案預設的小型量化模型：

```powershell
ollama pull qwen3.5:2b-q4_K_M
ollama list
streamlit run app.py
```

完成規則式分析後，開啟「本機 AI 問答」分頁並啟用 Ollama。LogCouncil 只會把已遮蔽常見秘密與 email、最多 30 筆的高價值事件送到 `http://localhost:11434`；LLM 選出的直接證據會由程式以遮蔽後的事件內容呈現，模型產生的可能原因則明確標示為推測。這項功能不需要 Ollama 帳號、外部 API key 或付費額度。

本機 Ollama 無法由 Streamlit Community Cloud 連線，因此公開部署仍使用原有規則式分析；使用本機 LLM 問答時，請在安裝 Ollama 的同一部電腦上執行 Streamlit。

#### 本機版與公開版的功能差異

| 執行方式 | 規則式多-Agent 分析 | 本機 AI 問答 |
| --- | --- | --- |
| 在安裝 Ollama 的電腦執行 `streamlit run app.py` | 可用 | 可用 |
| Streamlit Community Cloud 公開網站 | 可用 | **不可用** |

`localhost:11434` 對公開網站而言是 Streamlit 的遠端伺服器，不是使用者的電腦，因此 Community Cloud 無法連線到本機 Ollama。即使將本機 AI 問答程式碼合併至 `main`，也不會讓公開網站取得本機模型能力；若要讓公開網站提供 LLM 問答，仍需要外部模型 API，或另行部署一個可由公開網站連線的模型服務。請勿為了連接公開網站而直接將本機 Ollama 連接埠暴露到網際網路。

#### 本機 AI 問答測試案例

Repository 提供 [`examples/local-llm-qa-demo.log`](examples/local-llm-qa-demo.log)，可直接在本機 Streamlit 使用「上傳檔案」進行測試：

1. 上傳測試 Log 並按下「開始分析」。
2. 進入「本機 AI 問答」分頁。
3. 開啟「啟用本機 LLM 問答（Ollama）」。
4. 依序測試以下問題：

```text
這起事故發生了什麼？請依時間順序說明。
哪些事件直接支持資料庫連線池耗盡的推測？
目前能否確定資料庫伺服器曾經當機？為什麼？
服務是否已經恢復？請指出證據。
如果我是值班工程師，接下來最優先檢查哪三件事？
目前還缺少哪些資料，才能更有把握確認根因？
```

預期回答應辨識「慢查詢 → 連線池滿載 → 等待連線逾時 → checkout 回傳 503 → 延遲恢復」的時間線，並引用 `EVT-002` 至 `EVT-006`。回答可以將慢查詢造成連線池耗盡列為推測，但不能宣稱資料庫伺服器已當機，也不能捏造部署、CPU、記憶體或重試結果。模型回答仍可能有誤，應以畫面中的「直接證據」為準。

部署至 Streamlit Community Cloud 時，請使用根目錄的 `app.py` 與 Python 3.12。完整欄位與部署後檢查請參閱 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。

發布前必須確認 GitHub Actions 的 `CI / test-and-deployment-smoke` 為綠燈；它會在 Ubuntu／Python 3.12 執行完整 pytest 與 `app.py` 分析流程驗證。

隱私提醒：本機啟動時 log 留在本機程序；使用 Community Cloud 時，上傳內容會傳到 Streamlit 的雲端執行環境。LogCouncil 不會再把內容轉送至外部 LLM/API，但公開部署不等同本機處理，請勿上傳未獲授權的敏感 production logs。

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
