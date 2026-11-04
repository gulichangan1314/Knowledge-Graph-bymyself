"""Streamlit workbench for EnterpriseKG.

Runs in two honest modes:
* offline: reads the audited graph seed and alignment reports;
* online: executes read-only Cypher against Neo4j when Bolt is reachable.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    print("Streamlit is not installed. Run: python -m pip install -r requirements.txt")
    raise SystemExit(1)

from src.config import CONFIG, project_path
from src.graph_builder import build_graph_seed, write_seed
from src.graph_query import CYPHER_QUERIES, run_query
from src.pipeline import run_pipeline
from src.quality_check import run_quality_checks
from src.utils import json_load

st.set_page_config(
    page_title=str(CONFIG.get("ui", {}).get("page_title", "企业知识图谱工作台")),
    page_icon=str(CONFIG.get("ui", {}).get("page_icon", "🕸️")),
    layout=str(CONFIG.get("ui", {}).get("layout", "wide")),
)

st.markdown(
    """
<style>
  .block-container {padding-top: 1.4rem; padding-bottom: 2.5rem;}
  .ekg-hero {
    border: 1px solid #dbe5f0; border-radius: 16px; padding: 18px 22px;
    background: linear-gradient(110deg, #f7fbff 0%, #edf4ff 60%, #f8f7ff 100%);
    margin-bottom: 12px;
  }
  .ekg-hero h1 {margin: 0 0 4px 0; font-size: 1.7rem;}
  .ekg-hero p {margin: 0; color: #4b5b6b;}
  .ekg-pill {
    display: inline-block; padding: 2px 9px; border-radius: 999px;
    background: #eaf3ff; color: #1b5f9e; font-size: 0.78rem; margin-right: 6px;
  }
  div[data-testid="stMetricValue"] {font-size: 1.55rem;}
</style>
""",
    unsafe_allow_html=True,
)


def _neo4j_online() -> bool:
    uri = str(CONFIG["neo4j"]["uri"])
    parsed = urlparse(uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 7687
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@st.cache_data(show_spinner=False)
def load_artifacts() -> dict[str, Any]:
    processed = project_path(CONFIG, "processed_dir")
    output = project_path(CONFIG, "output_dir")
    entities_path = processed / "entities.json"
    matching_path = processed / "match_report.json"
    meta_path = processed / "pipeline_meta.json"

    if not entities_path.is_file() or not matching_path.is_file():
        run_pipeline(CONFIG, write=True)

    entities = json_load(entities_path)
    matching = json_load(matching_path)
    meta = json_load(meta_path) if meta_path.is_file() else {}

    seed_path = output / "graph_seed.json"
    if seed_path.is_file():
        seed = json_load(seed_path)
    else:
        seed = build_graph_seed(entities, matching)
        write_seed(seed, CONFIG)

    quality_path = output / "quality_report.json"
    quality = json_load(quality_path) if quality_path.is_file() else None
    return {
        "entities": entities,
        "matching": matching,
        "meta": meta,
        "seed": seed,
        "quality": quality,
    }


def _json_download(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _flags_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def _status_icon(status: str) -> str:
    return {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, status)


# Sidebar ------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🕸️ EnterpriseKG")
    online = _neo4j_online()
    if online:
        st.success("Neo4j Bolt 已连通")
    else:
        st.warning("Neo4j 未启动 · 当前为离线模式")
    st.caption(f"Bolt: `{CONFIG['neo4j']['uri']}`")
    st.caption("本地模式：Bolt 直连，无 Neo4j Browser")

    if st.button("↻ 重跑离线流水线", width="stretch"):
        with st.spinner("加载、清洗、对齐、构建图谱种子..."):
            result = run_pipeline(CONFIG, write=True)
            write_seed(build_graph_seed(result["entities"], result["matching"]), CONFIG)
        st.cache_data.clear()
        st.rerun()

    if st.button("🛡️ 重新运行质量检查", width="stretch"):
        with st.spinner("执行质量门禁..."):
            run_quality_checks(CONFIG, check_neo4j=online, require_neo4j=False)
        st.cache_data.clear()
        st.rerun()

    st.divider()
    with st.expander("启动顺序 / 常用命令"):
        st.code(
            "install_python.bat\n"
            "start_neo4j.bat\n"
            "run_pipeline.bat\n"
            "start_app.bat",
            language="text",
        )
        st.caption("本地 Neo4j 不需要 Docker；双击 start_neo4j.bat 即可。")
    st.divider()
    st.caption("数据仅来自项目内模拟 CSV；不联网下载业务数据。")

# Hero ---------------------------------------------------------------------
artifacts = load_artifacts()
entities = artifacts["entities"]
matching = artifacts["matching"]
seed = artifacts["seed"]
quality = artifacts["quality"]
stats = matching["stats"]

st.markdown(
    f"""
<div class="ekg-hero">
  <h1>企业知识图谱工作台</h1>
  <p>从 4 张模拟业务表出发，完成企业规范化、实体对齐、图谱构建与质量门禁。</p>
  <div style="margin-top:10px;">
    <span class="ekg-pill">Python 3.13</span>
    <span class="ekg-pill">rapidfuzz</span>
    <span class="ekg-pill">Neo4j 5.26</span>
    <span class="ekg-pill">Streamlit</span>
    <span class="ekg-pill">离线可审计</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

col_a, col_b, col_c, col_d, col_e = st.columns(5)
col_a.metric("原始企业", stats["raw_company_records"])
col_b.metric("规范化企业", stats["canonical_companies"], delta=f"-{stats['merged_variant_records']} 合并")
col_c.metric("名称别名", stats["aliases"])
col_d.metric("疑似未合并", stats["suspicious_company_pairs"])
col_e.metric("自动对齐提及", stats["auto_merged_mentions"])

tab_overview, tab_alignment, tab_graph, tab_quality = st.tabs(
    ["📊 数据总览", "🧬 实体对齐", "🕸️ 图谱查询", "🛡️ 质量检查"]
)

# Overview -----------------------------------------------------------------
with tab_overview:
    st.subheader("数据资产概览")
    left, right = st.columns([1.25, 1])
    with left:
        companies = pd.DataFrame(entities["companies"])
        display = companies[
            ["company_id", "name", "credit_code", "industry", "region_label", "quality_flags"]
        ].copy()
        display["credit_code"] = display["credit_code"].replace("", "(缺失)")
        display["quality_flags"] = display["quality_flags"].map(_flags_text)
        display.columns = ["ID", "企业名称", "信用代码", "行业", "地区", "质量标记"]
        st.dataframe(display, width="stretch", hide_index=True)

    with right:
        st.markdown("**实体与事实规模**")
        scale = pd.DataFrame(
            {
                "类别": ["企业", "自然人股东", "外部机构股东", "专利", "地区"],
                "数量": [
                    len(entities["companies"]),
                    len(entities["persons"]),
                    len(entities["external_organizations"]),
                    len(entities["patents"]),
                    len(entities["regions"]),
                ],
            }
        )
        st.bar_chart(scale.set_index("类别"), height=230)
        completeness = pd.DataFrame(
            {
                "表": ["companies", "shareholders", "patents", "regions"],
                "行数": [
                    len(entities["companies"]),
                    len(entities["relationships"]["shareholding"]),
                    len(entities["patents"]),
                    len(entities["regions"]),
                ],
            }
        )
        st.caption("原始数据为固定模拟集；空信用代码与名称冲突是被刻意注入的测试样例。")
        st.dataframe(completeness, width="stretch", hide_index=True)

    st.divider()
    st.subheader("刻意注入的数据问题")
    issue_cols = st.columns(3)
    issue_cols[0].info("**2 对近名不同码**\n\nC001/C002、C003/C004：名称接近，但信用代码不同，禁止自动合并。")
    issue_cols[1].info("**1 对同码不同名**\n\nC005/C006：同一信用代码，自动归并为 C005，C006 保留为别名。")
    issue_cols[2].info("**1 条缺失代码**\n\nC008 缺失信用代码，与 C007 名称接近，只能进入人工复核。")

    st.markdown("**专利申请人原始写法与对齐结果**")
    patent_rows = []
    resolved = {item["source_id"]: item for item in matching["resolved_mentions"]}
    review = {item["source_id"]: item for item in matching["review_mentions"]}
    for patent in entities["patents"]:
        source_id = patent["patent_id"]
        match = resolved.get(source_id)
        status = "自动对齐" if match else ("人工复核" if source_id in review else "未匹配")
        patent_rows.append(
            {
                "专利": patent["patent_name"],
                "申请人原文": patent["applicant_name"],
                "归一企业": match["company_name"] if match else "—",
                "对齐方式": match["method"] if match else (review.get(source_id, {}).get("conflicts", [""])[0] if source_id in review else "—"),
                "状态": status,
            }
        )
    st.dataframe(pd.DataFrame(patent_rows), width="stretch", hide_index=True)

# Alignment ----------------------------------------------------------------
with tab_alignment:
    st.subheader("实体对齐审核台")
    st.caption(
        "相似度分三层：high ≥ 88、medium ≥ 78、low < 78。"
        "是否合并由独立规则决定：不同非空信用代码为硬冲突，缺失代码最高只能人工复核。"
    )

    pairs = pd.DataFrame(matching["company_pairs"])
    if not pairs.empty:
        filter_cols = st.columns([1, 1, 2])
        tier_options = ["全部", "high", "medium", "low"]
        tier = filter_cols[0].selectbox("置信分层", tier_options)
        decision_options = ["全部", "review", "auto_merge"]
        decision = filter_cols[1].selectbox("决策", decision_options)
        keyword = filter_cols[2].text_input("按企业名筛选", placeholder="例如：星海")

        view = pairs.copy()
        if tier != "全部":
            view = view[view["confidence_tier"] == tier]
        if decision != "全部":
            view = view[view["decision"] == decision]
        if keyword:
            mask = view["left_name"].str.contains(keyword, na=False) | view["right_name"].str.contains(keyword, na=False)
            view = view[mask]

        table = view[
            ["candidate_id", "left_name", "left_credit_code", "right_name",
             "right_credit_code", "name_score", "score", "confidence_tier",
             "decision", "conflicts"]
        ].copy()
        table["conflicts"] = table["conflicts"].map(lambda value: ", ".join(value))
        table.columns = ["候选ID", "企业A", "代码A", "企业B", "代码B", "名称分",
                         "综合分", "置信分层", "决策", "冲突"]
        st.dataframe(table, width="stretch", hide_index=True)
        st.caption(f"当前展示 {len(view)} / {len(pairs)} 对。低分候选不会进入自动合并。")

        selected = st.selectbox(
            "查看候选详情",
            view["candidate_id"].tolist() if not view.empty else [],
            format_func=lambda value: next(
                (f"{row.left_name} ↔ {row.right_name}" for row in view.itertuples() if row.candidate_id == value),
                value,
            ),
        )
        if selected:
            item = next(row for row in matching["company_pairs"] if row["candidate_id"] == selected)
            detail_left, detail_right = st.columns(2)
            detail_left.markdown(
                f"**企业 A**  \n{item['left_name']}  \n代码：`{item['left_credit_code'] or '(缺失)'}`"
            )
            detail_right.markdown(
                f"**企业 B**  \n{item['right_name']}  \n代码：`{item['right_credit_code'] or '(缺失)'}`"
            )
            st.json(item, expanded=False)
    else:
        st.info("没有疑似未合并候选对。")

    st.divider()
    st.subheader("名称变体与曾用名")
    aliases = pd.DataFrame(matching["aliases"])
    if not aliases.empty:
        alias_view = aliases[
            ["canonical_company_id", "canonical_name", "name", "alias_type", "confidence", "method"]
        ].copy()
        alias_view.columns = ["规范企业ID", "规范名称", "别名/变体", "别名类型", "置信度", "方法"]
        st.dataframe(alias_view, width="stretch", hide_index=True)

    st.download_button(
        "⬇️ 下载对齐报告 (JSON)",
        data=_json_download(matching),
        file_name="match_report.json",
        mime="application/json",
    )

# Graph --------------------------------------------------------------------
with tab_graph:
    st.subheader("图谱查询")
    online = _neo4j_online()
    if online:
        st.success("Neo4j 在线，可执行只读 Cypher。")
        preset = st.selectbox(
            "内置查询",
            list(CYPHER_QUERIES),
            format_func=lambda key: f"{CYPHER_QUERIES[key]['title']} ({key})",
        )
        cypher = st.text_area("Cypher（只读）", value=CYPHER_QUERIES[preset]["cypher"], height=220)
        if st.button("▶ 执行查询", type="primary"):
            try:
                rows = run_query(cypher, config=CONFIG)
                if rows:
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                    st.caption(f"返回 {len(rows)} 行。")
                else:
                    st.info("查询成功，但没有结果。")
            except Exception as exc:  # noqa: BLE001
                st.error(f"查询失败：{type(exc).__name__}: {exc}")
    else:
        st.warning(
            "Neo4j 未连通，当前展示离线种子。双击 start_neo4j.bat 启动本地 Neo4j"
            "（无需 Docker），再运行 run_pipeline.bat 即可写入图数据库。"
        )
        node_counts = seed["meta"]["node_counts"]
        rel_counts = seed["meta"]["relationship_counts"]
        count_cols = st.columns(4)
        count_cols[0].metric("Company", node_counts.get("Company", 0))
        count_cols[1].metric("Patent", node_counts.get("Patent", 0))
        count_cols[2].metric("Person", node_counts.get("Person", 0))
        count_cols[3].metric("外部机构", node_counts.get("ExternalOrganization", 0))
        st.caption(f"关系：{rel_counts}")

        preset = st.selectbox(
            "查看内置 Cypher",
            list(CYPHER_QUERIES),
            format_func=lambda key: CYPHER_QUERIES[key]["title"],
        )
        st.code(CYPHER_QUERIES[preset]["cypher"], language="cypher")
        with st.expander("离线候选对预览", expanded=True):
            offline_rows = [
                {
                    "企业A": node["properties"]["left_name"],
                    "企业B": node["properties"]["right_name"],
                    "综合分": node["properties"]["score"],
                    "置信分层": node["properties"]["confidence_tier"],
                    "决策": node["properties"]["decision"],
                }
                for node in seed["nodes"]["MergeCandidate"]
            ]
            st.dataframe(pd.DataFrame(offline_rows), width="stretch", hide_index=True)

    st.divider()
    st.markdown("**关系模型**")
    st.code(
        "(Person|ExternalOrganization|Company)-[:HOLDS_SHARES]->(Company)\n"
        "(Company)-[:OWNS_PATENT]->(Patent)\n"
        "(Company)-[:LOCATED_IN]->(Region)\n"
        "(Company)-[:HAS_ALIAS]->(CompanyAlias)\n"
        "(Company)-[:SUSPECTED_DUPLICATE]->(Company)",
        language="cypher",
    )

# Quality ------------------------------------------------------------------
with tab_quality:
    st.subheader("质量门禁")
    if quality is None:
        st.info("尚未生成质量报告，请点击左侧“重新运行质量检查”。")
    else:
        overall = quality["overall_status"]
        if overall == "PASS":
            st.success(f"总体结果：{overall}")
        elif overall == "PASS_WITH_WARNINGS":
            st.warning(f"总体结果：{overall}（本地校验通过，在线 Neo4j 校验被跳过）")
        else:
            st.error(f"总体结果：{overall}")

        checks = quality["checks"]
        check_table = pd.DataFrame(
            [
                {
                    "状态": _status_icon(item["status"]),
                    "检查项": item["name"],
                    "说明": item["detail"],
                }
                for item in checks
            ]
        )
        st.dataframe(check_table, width="stretch", hide_index=True)

        suspicious = quality["suspected_unmerged_pairs"]
        st.markdown(f"**疑似未合并候选对：{len(suspicious)} 对**")
        if suspicious:
            pairs_table = pd.DataFrame(
                [
                    {
                        "企业A": item["left_name"],
                        "企业B": item["right_name"],
                        "名称分": item["name_score"],
                        "综合分": item["score"],
                        "分层": item["confidence_tier"],
                        "结论": item["decision"],
                    }
                    for item in suspicious
                ]
            )
            st.dataframe(pairs_table, width="stretch", hide_index=True)

        st.download_button(
            "⬇️ 下载质量报告 (JSON)",
            data=_json_download(quality),
            file_name="quality_report.json",
            mime="application/json",
        )
        st.caption(f"报告路径：{quality.get('report_path', '')}")

st.divider()
st.caption(
    "EnterpriseKG · 模拟数据 · 所有写操作限定在工作区 · "
    "Neo4j 未运行时自动降级为离线审计模式"
)
