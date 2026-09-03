from __future__ import annotations

import hashlib
from typing import Any

import streamlit as st

from log_council.qa import (
    DEFAULT_OLLAMA_MODEL,
    LogAnswer,
    OllamaError,
    OllamaProvider,
    OllamaUnavailableError,
)
from log_council.reporting import build_safe_report, serialize_report


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
AGENTS = (
    ("Pattern Agent", "尋找重複錯誤、burst 與異常模式"),
    ("Timeline Agent", "重建異常出現、擴散與恢復順序"),
    ("Correlation Agent", "依時間、服務與識別碼建立關聯"),
    ("Root Cause Agent", "比較並排序可能根因"),
    ("Reviewer Agent", "尋找反證、替代解釋與缺少的資料"),
)

AGENT_LABELS = {
    "Pattern Agent": "模式 Agent",
    "Timeline Agent": "時間線 Agent",
    "Correlation Agent": "關聯 Agent",
    "Root Cause Agent": "根因 Agent",
    "Reviewer Agent": "審查 Agent",
    "Coordinator": "協調器",
}

COLUMN_LABELS = {
    "id": "事件 ID",
    "timestamp": "時間",
    "level": "等級",
    "service": "服務",
    "message": "訊息",
    "event_id": "事件 ID",
    "reason": "證據理由",
    "stance": "證據立場",
    "source_event_id": "來源事件 ID",
    "target_event_id": "目標事件 ID",
    "relation": "關聯類型",
    "basis": "關聯依據",
    "delta_seconds": "時間差（秒）",
    "message_id": "訊息 ID",
    "run_id": "分析 ID",
    "sequence": "順序",
    "sender": "發送者",
    "recipient": "接收者",
    "kind": "訊息類型",
    "subject": "主旨",
    "body": "內容",
    "evidence_ids": "證據事件 ID",
    "payload_refs": "引用訊息",
    "in_reply_to": "回覆訊息 ID",
    "step": "步驟",
    "agent": "Agent",
    "action": "動作",
    "detail": "內容",
    "status": "狀態",
    "source": "來源 Agent",
    "target": "目標 Agent",
    "question": "問題",
    "input_lines": "輸入行數",
    "event_count": "事件數",
    "structured_count": "結構化事件數",
    "fallback_count": "非結構化保留數",
    "invalid_timestamp_count": "無效時間戳記數",
    "duplicate_id_count": "重複事件 ID 數",
    "coverage": "結構化解析率",
    "line_number": "行號",
    "code": "問題代碼",
    "raw": "原始內容",
}

VALUE_LABELS = {
    "supporting": "支持",
    "contradicting": "反證",
    "context": "背景資訊",
    "completed": "已完成",
    "task": "任務",
    "finding": "分析發現",
    "hypothesis": "假設",
    "review_request": "審查請求",
    "challenge": "質疑",
    "revision_request": "修訂請求",
    "revision": "修訂",
    "decision": "決策",
    "repeated-signature": "重複訊息特徵",
    "bounded-time-proximity": "限定時間鄰近",
}


def _display_value(value: Any) -> Any:
    if isinstance(value, str):
        if value in AGENT_LABELS:
            return AGENT_LABELS[value]
        if value in VALUE_LABELS:
            return VALUE_LABELS[value]
        if value.startswith("shared-"):
            return f"共用識別碼：{value.removeprefix('shared-')}"
    return value


def localized_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            COLUMN_LABELS.get(key, key): _display_value(value)
            for key, value in row.items()
        }
        for row in rows
    ]


def decode_upload(data: bytes) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"檔案超過 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB 上限")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("檔案不是有效的 UTF-8 文字") from exc


def input_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_text_size(text: str, limit: int = MAX_UPLOAD_BYTES) -> None:
    if len(text.encode("utf-8")) > limit:
        raise ValueError(f"輸入內容超過 {limit // (1024 * 1024)} MB 上限")


def cited_event_ids(payload: dict[str, Any]) -> list[str]:
    references: list[str] = []
    for finding in payload.get("findings", []):
        references.extend(item["event_id"] for item in finding.get("evidence", []))
    for hypothesis in payload.get("hypotheses", []):
        references.extend(item["event_id"] for item in hypothesis.get("supporting", []))
        references.extend(item["event_id"] for item in hypothesis.get("contradicting", []))
    for link in payload.get("correlations", []):
        references.extend((link["source_event_id"], link["target_event_id"]))
    for message in payload.get("agent_messages", []):
        references.extend(message.get("evidence_ids", []))
    return list(dict.fromkeys(references))


def _render_overview(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    stats = payload["parse"]["stats"]
    columns = st.columns(4)
    columns[0].metric("Log 事件數", f"{stats['event_count']:,}")
    columns[1].metric("結構化解析率", f"{stats['coverage']:.1%}")
    columns[2].metric("分析信心", f"{summary['confidence']:.0%}")
    columns[3].metric("Agent 共識", summary["consensus"])

    st.subheader("分析結論")
    leading = payload["hypotheses"][0]
    if summary["consensus_label"] == "high confidence":
        st.success(f"主要假設 · {leading['title']}")
    elif summary["consensus_label"] == "moderate confidence":
        st.warning(f"主要假設 · {leading['title']}")
    else:
        st.info(f"目前證據不足 · {leading['title']}")
    st.write(summary["root_cause"])
    st.caption(f"Reviewer 提醒：{summary['caveat']}")

    st.subheader("證據鏈")
    st.write(" → ".join(payload["evidence_chain"]))

    st.subheader("建議的下一步")
    for index, action in enumerate(payload["recommended_actions"], start=1):
        st.markdown(f"{index}. {action}")


def _render_evidence(payload: dict[str, Any]) -> None:
    st.subheader("事件關聯")
    correlations = payload.get("correlations", [])
    if correlations:
        st.dataframe(localized_rows(correlations), width="stretch", hide_index=True)
    else:
        st.info("目前沒有足夠資料建立事件之間的關聯。")

    st.subheader("根因假設排序")
    for index, hypothesis in enumerate(payload["hypotheses"], start=1):
        with st.expander(
            f"{index}. {hypothesis['title']} · {hypothesis['confidence']:.0%}",
            expanded=index == 1,
        ):
            st.write(hypothesis["explanation"])
            supporting = hypothesis.get("supporting", [])
            contradicting = hypothesis.get("contradicting", [])
            if supporting:
                st.markdown("**支持證據**")
                st.dataframe(localized_rows(supporting), width="stretch", hide_index=True)
            if contradicting:
                st.markdown("**反對證據**")
                st.dataframe(localized_rows(contradicting), width="stretch", hide_index=True)

    st.subheader("檢視被引用的原始事件")
    references = cited_event_ids(payload)
    events = {event["id"]: event for event in payload.get("events", [])}
    available = [event_id for event_id in references if event_id in events]
    if not available:
        st.info("這份報告沒有可檢視的引用事件。")
        return
    selected = st.selectbox("證據事件 ID", available)
    event = events[selected]
    st.json(localized_rows([{key: value for key, value in event.items() if key != "raw"}])[0])
    st.code(event.get("raw") or event.get("message", ""), language="text")


def _render_agents(payload: dict[str, Any]) -> None:
    st.subheader("Agent 分析結果")
    for finding in payload["findings"]:
        with st.expander(
            f"{AGENT_LABELS.get(finding['agent'], finding['agent'])} · {finding['title']} · {finding['confidence']:.0%}",
            expanded=finding["agent"] == "Root Cause Agent",
        ):
            st.write(finding["summary"])
            if finding.get("details"):
                for detail in finding["details"]:
                    st.markdown(f"- {detail}")
            if finding.get("evidence"):
                st.dataframe(localized_rows(finding["evidence"]), width="stretch", hide_index=True)


def _render_handoffs(payload: dict[str, Any]) -> None:
    st.subheader("Agent 訊息紀錄")
    st.caption("訊息順序、回覆對象、資料內容與證據引用都經過合約驗證。")
    st.dataframe(localized_rows(payload["agent_messages"]), width="stretch", hide_index=True)

    st.subheader("協調器活動")
    st.dataframe(localized_rows(payload["activities"]), width="stretch", hide_index=True)

    st.subheader("推理交接")
    st.dataframe(localized_rows(payload["handoffs"]), width="stretch", hide_index=True)


def _render_data_quality(payload: dict[str, Any]) -> None:
    parse = payload["parse"]
    stats = parse["stats"]
    st.subheader("解析品質")
    st.json(localized_rows([stats])[0])
    issues = parse["issues"]
    if issues:
        st.warning(f"保留了 {len(issues)} 個資料品質問題；沒有任何非空白行被靜默丟棄。")
        st.dataframe(localized_rows(issues), width="stretch", hide_index=True)
    else:
        st.success("所有非空白行都已解析，沒有資料品質問題。")

    events = payload.get("events", [])
    st.subheader("已遮蔽敏感資訊的事件預覽")
    if len(events) > 500:
        st.caption(f"共 {len(events):,} 筆；畫面僅顯示前 500 筆，下載報告仍包含全部事件。")
    preview = [
        {
            "id": event["id"],
            "timestamp": event["timestamp"],
            "level": event["level"],
            "service": event["service"],
            "message": event["message"],
        }
        for event in events[:500]
    ]
    st.dataframe(localized_rows(preview), width="stretch", hide_index=True)


def _render_qa_answer(answer: LogAnswer) -> None:
    st.write(answer.summary)

    st.markdown("**直接證據**")
    for fact in answer.facts:
        st.code(
            f"{fact.event_id} | {fact.timestamp} | {fact.level} | "
            f"{fact.service} | {fact.message}",
            language="text",
        )

    if answer.hypotheses:
        st.markdown("**可能原因（推測）**")
        confidence_labels = {"high": "高", "medium": "中", "low": "低"}
        for hypothesis in answer.hypotheses:
            references = ", ".join(hypothesis.evidence_ids)
            confidence = confidence_labels[hypothesis.confidence]
            st.markdown(
                f"- {hypothesis.statement}（信心：{confidence}；證據：{references}）"
            )

    if answer.next_actions:
        st.markdown("**建議檢查步驟**")
        for index, action in enumerate(answer.next_actions, start=1):
            st.markdown(f"{index}. {action.action}  \n   原因：{action.reason}")

    if answer.limitations:
        st.markdown("**目前限制**")
        for limitation in answer.limitations:
            st.warning(limitation)

    st.caption(f"本機模型：{answer.model} · 回答可能有誤，操作前請核對直接證據。")


def _render_local_qa(payload: dict[str, Any]) -> None:
    st.subheader("本機 LLM 問答")
    st.caption(
        "選用功能：遮蔽常見秘密與 email 後的證據會送到本機 Ollama（localhost），"
        "不使用外部 API，也不會自動執行任何建議。"
    )
    st.info(
        "這項功能只適用於在自己電腦上執行的 LogCouncil。"
        "Streamlit Community Cloud 無法連線到你電腦上的 Ollama。"
    )

    enabled = st.toggle(
        "啟用本機 LLM 問答（Ollama）",
        value=False,
        key="local_qa_enabled",
    )
    if not enabled:
        st.caption("預設關閉；目前報告仍完全由可重播的規則式 Agents 產生。")
        return

    health_provider = OllamaProvider(model=DEFAULT_OLLAMA_MODEL, timeout_seconds=3)
    try:
        version = health_provider.healthcheck()
    except OllamaUnavailableError as exc:
        st.error(str(exc))
        st.code("ollama serve", language="powershell")
        return
    except OllamaError as exc:
        st.error(f"Ollama 狀態檢查失敗：{exc}")
        return

    st.success(f"Ollama {version} 已連線 · {DEFAULT_OLLAMA_MODEL}")
    run_id = payload.get("run_id", "")
    if st.session_state.get("local_qa_run_id") != run_id:
        st.session_state["local_qa_history"] = []
        st.session_state["local_qa_run_id"] = run_id

    history = st.session_state.setdefault("local_qa_history", [])
    for item in history:
        with st.chat_message("user"):
            st.write(item["question"])
        with st.chat_message("assistant"):
            _render_qa_answer(item["answer"])

    question = st.chat_input(
        "例如：發生了什麼問題？我接下來應該先檢查什麼？",
        key="local_qa_question",
    )
    if question:
        answer_provider = OllamaProvider(
            model=DEFAULT_OLLAMA_MODEL,
            timeout_seconds=120,
        )
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("本機模型正在閱讀已篩選的證據…"):
                try:
                    answer = answer_provider.answer(question, payload)
                except OllamaUnavailableError as exc:
                    st.error(str(exc))
                except OllamaError as exc:
                    st.error(f"本機模型無法完成回答：{exc}")
                except ValueError as exc:
                    st.error(f"無法建立問答證據：{exc}")
                else:
                    _render_qa_answer(answer)
                    history.append({"question": question, "answer": answer})


def _render_report(payload: dict[str, Any]) -> None:
    st.divider()
    st.caption(f"分析 ID · {payload['run_id']}")
    overview, evidence, agents, handoffs, quality, qa = st.tabs([
        "總覽",
        "證據",
        "Agent 分析",
        "交接紀錄",
        "資料品質",
        "本機 AI 問答",
    ])
    with overview:
        _render_overview(payload)
    with evidence:
        _render_evidence(payload)
    with agents:
        _render_agents(payload)
    with handoffs:
        _render_handoffs(payload)
    with quality:
        _render_data_quality(payload)
    with qa:
        _render_local_qa(payload)

    st.download_button(
        "下載安全 JSON 報告",
        data=serialize_report(payload),
        file_name=f"log-council-{payload['run_id']}.json",
        mime="application/json",
        width="stretch",
    )


def main() -> None:
    st.set_page_config(
        page_title="LogCouncil",
        page_icon="🔎",
        layout="wide",
    )
    st.title("LogCouncil")
    st.markdown("**把 log 交給一組可稽核的 Agents，取得證據導向的事故解釋與下一步。**")
    st.caption("本機優先 · 僅分析 log · 僅提供唯讀建議 · 不需要 API key")

    with st.sidebar:
        st.header("分析團隊")
        for name, responsibility in AGENTS:
            st.markdown(f"**{AGENT_LABELS.get(name, name)}**  \n{responsibility}")
        st.divider()
        st.info(
            "分析只在執行 LogCouncil 的環境中完成，不會送往外部 LLM/API。"
            "若啟用本機 LLM，只有遮蔽常見秘密與 email 後的證據會傳給 localhost Ollama。"
            "若使用 Community Cloud，上傳內容會進入該雲端執行環境。"
            "畫面與下載報告會遮蔽常見秘密；原始輸入不會被修改。"
        )

    mode = st.radio("輸入方式", ("貼上 log", "上傳檔案"), horizontal=True)
    input_text = ""
    input_error: str | None = None
    if mode == "貼上 log":
        input_text = st.text_area(
            "Log 內容",
            height=220,
            placeholder=(
                '{"ts":"2026-09-03T10:00:00Z","level":"ERROR",'
                '"service":"checkout","message":"request timeout"}'
            ),
        )
    else:
        upload = st.file_uploader(
            "選擇 UTF-8 log",
            type=("log", "txt", "jsonl"),
            help="最大 50 MB；檔案只在目前的 LogCouncil 執行環境中分析。",
        )
        if upload is not None:
            try:
                input_text = decode_upload(upload.getvalue())
            except ValueError as exc:
                input_error = str(exc)
                st.error(input_error)

    analyze = st.button("開始分析", type="primary", width="stretch")
    if analyze:
        if input_error:
            st.error("請先修正輸入檔案。")
        elif not input_text.strip():
            st.error("請貼上 log 或選擇一個 log 檔案。")
        else:
            try:
                validate_text_size(input_text)
            except ValueError as exc:
                st.error(str(exc))
            else:
                with st.spinner("五個 Agents 正在比對證據…"):
                    try:
                        payload = build_safe_report(input_text, include_events=True)
                    except Exception as exc:  # UI boundary: failures must remain visible
                        st.session_state.pop("analysis_payload", None)
                        st.error(f"分析失敗：{exc}")
                    else:
                        st.session_state["analysis_payload"] = payload
                        st.session_state["analysis_digest"] = input_digest(input_text)

    payload = st.session_state.get("analysis_payload")
    if payload is not None:
        if input_digest(input_text) != st.session_state.get("analysis_digest"):
            st.warning("輸入內容已變更；請重新按「開始分析」以更新結果。")
        else:
            _render_report(payload)


if __name__ == "__main__":
    main()
