# EnterpriseKG 交付说明

> 一个无需 Docker 的轻量级企业知识图谱项目：从模拟 CSV 到清洗、实体对齐、真实 Neo4j 图数据库、Cypher 查询、质量门禁和 Streamlit 工作台。

---

## 1. 这个程序能做什么

| 能力 | 具体功能 |
|---|---|
| 数据接入 | 读取 4 张 UTF-8、英文表头 CSV，校验必需列、空表、主键、行数契约 |
| 数据清洗 | 名称 NFKC 规范化、信用代码归一化/18 位校验、日期/金额/比例解析、逐行质量标记 |
| 实体抽取 | 企业、自然人、外部机构股东、专利、地区；抽取专利申请人、持股目标、机构股东等 mentions |
| 实体对齐 | rapidfuzz `WRatio` 名称匹配；信用代码强一致；曾用名；同码名称变体；置信度分层 |
| 冲突处理 | 不同信用代码硬禁止合并；缺代码最高人工复核；同名多实体消歧；不做链式传递合并 |
| 图谱构建 | 生成可审计的离线 `graph_seed.json`，并 MERGE 到真实 Neo4j（节点/关系/约束） |
| 图查询 | 企业总览、疑似未合并候选、股权—专利二跳链路、别名查询；CLI 与 Streamlit 两种入口 |
| 质量门禁 | 12 项检查：数据契约、代码完整性、冲突识别、曾用名、合并安全性、图完整性、在线 Neo4j 节点数 |
| 人工审核 | 输出 `match_report.json`、`match_candidates.csv`，每条候选带分数、分层、决策、冲突和理由 |
| 可视化 | Streamlit：数据总览、实体对齐审核台、在线 Cypher 查询、质量报告 |
| 一键运行 | Windows `.bat` 引导 Python/venv/本地 Neo4j；Docker Compose 作为可选方案保留 |

### 业务问题样例

- 两家公司名字非常像，但信用代码不同，能不能合并？→ **不能自动合并，进入 review，并写入 `SUSPECTED_DUPLICATE` 边**。
- 同一信用代码出现两个名称写法，怎么处理？→ **自动归并，保留 canonical 企业和 `CompanyAlias` 别名节点**。
- 专利申请人写的是企业旧称，怎么对齐？→ **命中登记曾用名，生成 `OWNS_PATENT` 边**。
- 某企业缺信用代码，但名称和另一家高度相似？→ **最高只能 review，不伪造代码，不自动合并**。

---

## 2. 当前验证结果

| 项目 | 结果 |
|---|---|
| 原始数据 | companies 8、shareholders 10、patents 8、regions 3 |
| 规范化企业 | 7 家 canonical（C006 归并为 C005 别名） |
| 图节点 | 34 |
| 图关系 | 30 |
| 疑似未合并候选 | 3 对，全部 `review` |
| 在线质量检查 | **12/12 PASS** |
| 单元测试 | **19 tests OK** |
| Streamlit | HTTP 200；AppTest 0 exceptions |
| 持久化 | 停止/重启后仍有 7 家 Company |
| Docker | 不使用；当前用工作区便携 Neo4j 5.26.32 |

三条核心 Cypher 实测：

| 查询 | 返回 |
|---|---:|
| 企业总览 | 7 行 |
| 疑似未合并候选对 | 3 行 |
| 股权—专利二跳链路 | 12 行 |

---

## 3. 两种压缩包

### A. `EnterpriseKG_source_*.zip` — 轻量源码/文档包

适合查看代码、归档、二次开发。

- 包含全部源码、测试、配置、原始 CSV、处理产物、质量报告、启动脚本、文档；
- **不包含** `venv`、`.runtime`、缓存；
- 需要按照 `install_python.bat` 重新创建 Python 环境；
- Neo4j 可用工作区便携运行时重建，或改用 Docker。

### B. `EnterpriseKG_portable_*.zip` — 免 Docker 运行包

适合在当前机器直接继续使用。

- 在上面的内容基础上，额外包含：
  - `EnterpriseKG/.runtime/jre`：Temurin JRE 21；
  - `EnterpriseKG/.runtime/lib`：Neo4j 5.26.32 运行 JAR；
  - `EnterpriseKG/.runtime/neo4j-home`：已经建好的持久化图数据；
  - `EnterpriseKG/local_neo4j/target/classes`：本地启动类。
- **仍不包含 `venv`**：虚拟环境含有绝对路径，跨目录复制不可靠。首次使用先运行 `install_python.bat` 重建 venv。
- 本机已有 Python 3.13.15，通常只需安装依赖。

> 两个包都不包含 `.env`（避免携带本地配置）；Docker 模式请复制 `.env.example` 为 `.env`。本地模式不需要 `.env`，认证关闭且只监听 `127.0.0.1`。

---

## 4. 解压后怎么用

### 首次

```powershell
# 1. 在解压目录双击，或执行
.\install_python.bat

# 2. 启动本地 Neo4j（无需 Docker，首次约 30–60 秒）
.\start_neo4j.bat

# 3. 建图 + 质量检查 + 测试
.\run_pipeline.bat

# 4. 打开工作台
.\start_app.bat
```

访问 <http://127.0.0.1:8501>。

### 日常

```powershell
.\start_neo4j.bat
.\start_app.bat
```

关闭 Neo4j 控制台会停止数据库，但数据在 `EnterpriseKG/.runtime/neo4j-home`，下次启动仍在。

### 只有源码包时

源码包没有 `.runtime`，需要：

- 安装 Docker 后使用 `docker compose up -d`；或
- 按 `EnterpriseKG/local_neo4j/README.md` 重建本地便携运行时。

---

## 5. 三条核心 Cypher

```cypher
// 1. 企业总览
MATCH (c:Company)
OPTIONAL MATCH (c)-[:OWNS_PATENT]->(p:Patent)
OPTIONAL MATCH (c)-[:HAS_ALIAS]->(a:CompanyAlias)
RETURN c.name AS company,
       coalesce(c.credit_code, '(missing)') AS credit_code,
       c.industry AS industry,
       count(DISTINCT p) AS patents,
       count(DISTINCT a) AS aliases
ORDER BY patents DESC, company;

// 2. 疑似未合并候选对
MATCH (a:Company)-[r:SUSPECTED_DUPLICATE]->(b:Company)
RETURN a.name AS company_a,
       coalesce(a.credit_code, '(missing)') AS credit_code_a,
       b.name AS company_b,
       coalesce(b.credit_code, '(missing)') AS credit_code_b,
       r.score AS score,
       r.confidence_tier AS confidence,
       r.decision AS decision,
       r.conflicts AS conflicts
ORDER BY score DESC, company_a;

// 3. 股权—专利二跳链路
MATCH (holder)-[h:HOLDS_SHARES]->(c:Company)-[o:OWNS_PATENT]->(p:Patent)
RETURN labels(holder)[0] AS holder_type,
       holder.name AS holder,
       c.name AS company,
       p.patent_name AS patent,
       h.percentage AS ownership_pct,
       o.score AS alignment_score
ORDER BY company, holder, patent;
```

命令行入口：

```powershell
cd EnterpriseKG
.\venv\Scripts\python.exe -m src.graph_query --preset overview
.\venv\Scripts\python.exe -m src.graph_query --preset duplicates
.\venv\Scripts\python.exe -m src.graph_query --preset chain
```

---

## 6. 技术亮点

1. **置信度与合并权限分离**：`confidence_tier` 回答“有多像”，`decision` 回答“能不能合”。C007/C008 相似度 94.86（high），但 C008 缺代码，仍然是 review。
2. **信用代码硬闸门**：两个非空代码不同，即使名称相同也不自动合并。
3. **同码别名归并**：C006 自动归入 C005，保留 `CompanyAlias` 与 `HAS_ALIAS`，可追溯。
4. **曾用名强对齐**：P003/P007 通过登记曾用名对齐，而不是模糊猜测。
5. **未合并也留痕**：`MergeCandidate` 节点 + `SUSPECTED_DUPLICATE` 边，面板可审核。
6. **离线优先**：数据库不可达时仍生成图种子，不伪造在线状态。
7. **真实 Neo4j**：本地模式仍是 Neo4j 5.26.32 引擎和 Bolt 协议，不是 NetworkX 模拟。

---

## 7. 重要限制

- 本地嵌入式模式 **没有 Neo4j Browser / 7474 HTTP**，请用 Streamlit 或 `graph_query`。
- 本地模式关闭认证，只绑定 `127.0.0.1`，禁止暴露公网。
- 信用代码只校验 18 位格式，不校验 GB 32100 校验位。
- 企业两两比较是 O(n²)，当前数据量很小；上万企业应加 blocking。
- 当前包不包含 `venv`，因为 venv 不可跨目录可靠迁移；请重建。

---

## 8. 主要文件

| 文件 | 用途 |
|---|---|
| `README.md` | 新手开荒、Cypher、Docker-free 启动 |
| `EnterpriseKG/README.md` | 技术架构、数据契约、匹配规则、CLI |
| `EnterpriseKG/local_neo4j/README.md` | 便携 Neo4j 构建、启动、重置 |
| `EnterpriseKG/src/entity_matcher.py` | 实体对齐与冲突处理核心 |
| `EnterpriseKG/src/graph_builder.py` | 图种子与 Neo4j 写入 |
| `EnterpriseKG/src/quality_check.py` | 12 项质量门禁 |
| `EnterpriseKG/app/main.py` | Streamlit 工作台 |
| `EnterpriseKG/data/output/quality_report.json` | 最近一次质量报告 |
| `EnterpriseKG/data/output/graph_build_status.json` | 最近一次建图连接状态 |
| `start_neo4j.bat` | 无需 Docker 的一键启动入口 |
