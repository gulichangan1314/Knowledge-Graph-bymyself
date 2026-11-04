# EnterpriseKG · 企业知识图谱（Docker-free 本机版）

> 从 4 张模拟 CSV 出发，完成 **数据清洗 → 实体抽取 → rapidfuzz 名称对齐 → 真实 Neo4j 建图 → Cypher 查询 → 质量门禁** 的轻量级企业知识图谱项目。
> Docker 安装失败后，已改为 **工作区便携 Neo4j**；不需要 Docker、不需要系统级安装。

---

## 0. 新手开荒指南（先看这里）

### 当前真实状态（2026-11-04 12:00）

| 检查项 | 实际结果 |
|---|---|
| 操作系统 | Windows 11（10.0.26200，AMD64） |
| Python | **3.13.15 已安装**，`py -3.13` 可用 |
| Docker | **安装失败，已放弃**；项目不再依赖 Docker |
| Neo4j | **5.26.32 嵌入式运行时已启动**，Bolt `bolt://127.0.0.1:7687` |
| 数据持久化 | **已验证**：停止/重启后仍有 7 家 Company |
| 图规模 | 34 个节点、30 条关系、3 条 `SUSPECTED_DUPLICATE` 边 |
| 质量门禁 | **12/12 PASS**（含在线 Neo4j 校验） |
| 单元测试 | **19 tests OK** |
| 三条 Cypher | **已实际执行并返回结果** |

> **不需要安装 Docker。** Neo4j 直接运行在工作区 `.runtime` 内，使用官方 Maven 构件和便携 JRE；不写 PATH、不注册 Windows 服务、不装全局 Java。

### 第一步：双击 `install_python.bat`

- 检测 Python；已有 3.13 就跳过下载；
- 复用/创建 `EnterpriseKG\venv`；
- 如果依赖已存在，直接跳过下载；
- 跑一遍离线质量门禁，确认 Python 侧可用。

> 当前工作区已经完成，重复双击只会做检查，不会重复下载。

### 第二步：双击 `start_neo4j.bat`

这是 **Docker-free** 启动：

- 自动优先使用 `EnterpriseKG\.runtime` 里的便携 Neo4j；
- 首次启动约 **30–60 秒**，控制台会打印 `LOCAL_NEO4J_READY`；
- 数据保存在 `EnterpriseKG\.runtime\neo4j-home`，重启不丢；
- 使用期间请保持该控制台窗口打开；关闭窗口即停止本地图数据库。

你也可以单独双击 `start_neo4j_local.bat`。如果 7687 已在监听，脚本会提示 “already listening”，不会重复启动。

### 第三步：双击 `run_pipeline.bat`

依次执行：

1. `python -m src.graph_builder --reset`：把实体和关系真实写入本地 Neo4j；
2. `python -m src.quality_check`：12 项质量检查（含在线节点数校验）；
3. `python -m unittest discover -s tests -v`：19 个测试。

### 第四步：双击 `start_app.bat`

打开 <http://127.0.0.1:8501>，查看数据总览、实体对齐候选、在线图谱查询和质量报告。

> 本地嵌入式模式 **没有 Neo4j Browser**（`7474` 不监听），这是预期行为；UI 由 Streamlit 提供，Cypher 由 Python 驱动执行。Docker 模式下仍可用 Browser。

---

## 1. 为什么不用 Docker

| 问题 | 处理 |
|---|---|
| Docker Desktop 安装失败 | 不再要求 Docker |
| 官方 Neo4j 二进制 CDN 对当前地区返回 403 | 改用 **Maven Central 的官方 Neo4j 构件** |
| 机器没有 Java | 下载 **便携 Temurin JRE 21** 到工作区 |
| 不想写系统目录/注册表 | 所有运行时放在 `EnterpriseKG\.runtime`，只监听 `127.0.0.1` |

本项目当前默认使用 **Neo4j 5.26.32 嵌入式引擎 + Bolt 连接器**，Python 侧仍然完全使用官方 `neo4j` 驱动，Cypher 语法不变。

Docker 文件仍然保留（`docker-compose.yml`），只是**可选**；在能正常使用 Docker 的机器上仍可切换。

---

## 2. 已验证结果

| 验证项 | 结果 |
|---|---|
| 原始数据 | companies 8、shareholders 10、patents 8、regions 3 |
| 规范化企业 | 8 条原始记录 → 7 家 canonical（C006 归并为 C005 别名） |
| 名称对齐 | rapidfuzz 3.14.6；17 条自动对齐、1 条复核、4 条未匹配 |
| 图节点 | Company 7、Alias 3、Person 6、ExternalOrganization 4、Patent 8、Region 3、MergeCandidate 3 = **34** |
| 图关系 | HOLDS_SHARES 10、OWNS_PATENT 7、HAS_ALIAS 3、LOCATED_IN 7、SUSPECTED_DUPLICATE 3 = **30** |
| 持久化 | 停止后重启，`MATCH (n:Company) RETURN count(n)` 仍为 **7** |
| 质量检查 | **12 PASS / 0 WARN / 0 FAIL** |
| 单元测试 | **19 tests OK** |
| Streamlit | HTTP 200，AppTest 0 exceptions |

### 当前三组“疑似未合并”候选

| 企业 A | 企业 B | 综合分 | 分层 | 决策 | 冲突 |
|---|---|---:|---|---|---|
| 云岭新能源（深圳）集团有限公司 | 云岭新能源（深圳）有限公司 | 94.86 | high | review | 缺信用代码 |
| 星海智能装备股份有限公司 | 星海智能装备（苏州）股份有限公司 | 81.71 | medium | review | 代码不同 |
| 华夏天元科技有限公司 | 华夏天元科技（北京）有限公司 | 80.00 | medium | review | 代码不同 |

---

## 3. 三条核心 Cypher（已实测）

在 Streamlit「图谱查询」页执行，或使用：

```powershell
cd EnterpriseKG
.\venv\Scripts\python.exe -m src.graph_query --preset duplicates
```

### 查询 1：企业总览

```cypher
MATCH (c:Company)
OPTIONAL MATCH (c)-[:OWNS_PATENT]->(p:Patent)
OPTIONAL MATCH (c)-[:HAS_ALIAS]->(a:CompanyAlias)
RETURN c.name AS company,
       coalesce(c.credit_code, '(missing)') AS credit_code,
       c.industry AS industry,
       count(DISTINCT p) AS patents,
       count(DISTINCT a) AS aliases
ORDER BY patents DESC, company;
```

实测返回 7 行；C005 蓝海数据服务有限公司有 2 件专利，其余企业 0–1 件。

### 查询 2：疑似未合并候选对

```cypher
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
```

实测返回 3 行：云岭 94.86 / 星海 81.71 / 华夏 80.00，全部 `review`，没有自动合并。

### 查询 3：股权—专利二跳链路

```cypher
MATCH (holder)-[h:HOLDS_SHARES]->(c:Company)-[o:OWNS_PATENT]->(p:Patent)
RETURN labels(holder)[0] AS holder_type,
       holder.name AS holder,
       c.name AS company,
       p.patent_name AS patent,
       h.percentage AS ownership_pct,
       o.score AS alignment_score
ORDER BY company, holder, patent;
```

实测返回 12 行，覆盖自然人和企业股东到专利的二跳链路。

---

## 4. 项目结构

```text
工作区/
├── install_python.bat / .sh       # 第一步：Python 引导
├── start_neo4j.bat                # 第二步：优先启动工作区便携 Neo4j
├── start_neo4j_local.bat          # 仅本地 Neo4j（无 Docker）
├── stop_neo4j.bat / _local.bat    # 停止
├── run_pipeline.bat / .sh         # 第三步：建图 + 质量 + 测试
├── start_app.bat / .sh            # 第四步：Streamlit
├── bootstrap.bat / .sh            # venv + 依赖 + 离线自检
├── docker-compose.yml             # 可选 Docker 方案（当前不使用）
├── requirements.txt
└── EnterpriseKG/
    ├── data/raw/                  # 4 张模拟 CSV
    ├── data/processed/            # 清洗、实体、对齐报告
    ├── data/output/               # 图种子、质量报告、建图状态
    ├── src/
    │   ├── data_loader.py
    │   ├── data_cleaner.py
    │   ├── entity_extractor.py
    │   ├── entity_matcher.py
    │   ├── graph_builder.py
    │   ├── graph_query.py
    │   ├── quality_check.py
    │   ├── pipeline.py
    │   ├── config.py
    │   ├── models.py
    │   └── utils.py
    ├── app/main.py                # Streamlit
    ├── config/config.yaml
    ├── tests/                     # 19 个测试
    ├── local_neo4j/               # 无 Docker 的嵌入式运行时源码/说明
    ├── .runtime/                   # 便携 JRE、Neo4j 依赖、持久化数据（已生成）
    ├── venv/                      # 项目虚拟环境（已生成）
    ├── requirements.txt
    └── README.md
```

---

## 5. 模拟数据设计

| 文件 | 行数 | 刻意注入的问题 |
|---|---:|---|
| [companies.csv](EnterpriseKG/data/raw/companies.csv) | 8 | 2 对近名不同码：C001/C002、C003/C004；1 对同码不同名：C005/C006；1 条缺代码：C008 |
| [shareholders.csv](EnterpriseKG/data/raw/shareholders.csv) | 10 | 6 名自然人 + 4 家企业股东 |
| [patents.csv](EnterpriseKG/data/raw/patents.csv) | 8 | P003/P007 使用曾用名，P005 使用同码名称变体 |
| [regions.csv](EnterpriseKG/data/raw/regions.csv) | 3 | 北京海淀、苏州工业园区、深圳南山 |

---

## 6. 技术亮点

### 6.1 置信度与合并权限分离

| 维度 | 取值 | 含义 |
|---|---|---|
| `confidence_tier` | `high ≥ 88`、`medium ≥ 78`、`low < 78` | 名称/上下文有多像 |
| `decision` | `auto_merge` / `review` / `keep_separate` | 规则是否允许合并 |

典型例子：C007/C008 综合分 **94.86（high）**，但 C008 缺信用代码，所以 **review**，绝不自动合并。

### 6.2 冲突处理优先级

```text
有效统一社会信用代码 > 登记曾用名 > 同代码名称变体 > 精确名称 > rapidfuzz 模糊证据
```

- 两个非空信用代码不同 → **硬禁止自动合并**，即使名称完全相同；
- 一方缺代码 → **最高 review**，不会污染有代码的企业；
- 同代码不同名称 → 自动归并，C006 成为 C005 的 `CompanyAlias`；
- 多个企业同名 → `ambiguous_name`，人工消歧；
- **不做跨代码传递合并**；
- 未合并的候选保留为 `MergeCandidate` 节点 + `SUSPECTED_DUPLICATE` 边。

### 6.3 可审计、可复现

- 每个候选都有 `score / confidence_tier / decision / conflicts / reasons`；
- `graph_seed.json` 是建图前快照；
- `quality_report.json` 记录 12 项门禁；
- `graph_build_status.json` 记录真实在线状态、节点数、连接 URI；
- 质量检查曾实际拦截并修正 17 位信用代码，说明门禁不是摆设。

### 6.4 Docker-free 但不降级为假图数据库

本地运行时仍是 **Neo4j 5.26.32 引擎 + 官方 Bolt 协议**，不是 NetworkX/SQLite 模拟。
Python 代码、Cypher、Neo4j 驱动完全复用；只替换了启动方式。

---

## 7. 本地 Neo4j 运行细节

| 项目 | 位置/值 |
|---|---|
| 引擎 | Neo4j Community 5.26.32（官方 Maven 构件） |
| 数据目录 | `EnterpriseKG\.runtime\neo4j-home` |
| Bolt | `bolt://127.0.0.1:7687` |
| 便携 JRE | `EnterpriseKG\.runtime\jre` |
| 依赖 JAR | `EnterpriseKG\.runtime\lib` |
| 本地认证 | 嵌入式本地模式关闭认证，仅绑定 loopback |
| 启动脚本 | [start_neo4j_local.bat](start_neo4j_local.bat) |
| 详细说明 | [local_neo4j/README.md](EnterpriseKG/local_neo4j/README.md) |

重装/重建（仅当 `.runtime` 被删除时）见 [local_neo4j/README.md](EnterpriseKG/local_neo4j/README.md)。

重置图谱：

```powershell
.\stop_neo4j.bat
Remove-Item -Recurse -Force EnterpriseKG\.runtime\neo4j-home
.\start_neo4j.bat
.\run_pipeline.bat
```

---

## 8. 常用命令

```powershell
# Python 环境/自检
.\install_python.bat
.\bootstrap.bat

# 本地 Neo4j
.\start_neo4j.bat
.\stop_neo4j.bat

# 全链路（本地 Neo4j 已启动时真实写入）
.\run_pipeline.bat

# 单模块
cd EnterpriseKG
.\venv\Scripts\python.exe -m src.quality_check
.\venv\Scripts\python.exe -m src.graph_query --preset overview
.\venv\Scripts\python.exe -m src.graph_query --preset duplicates
.\venv\Scripts\python.exe -m src.graph_query --preset chain
.\venv\Scripts\python.exe -m unittest discover -s tests -v

# Streamlit
.\venv\Scripts\python.exe -m streamlit run app\main.py
```

---

## 9. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `start_neo4j.bat` 提示 already listening | 本地 Neo4j 已在运行 | 直接 `run_pipeline.bat` 或打开 Streamlit |
| 启动后 30–60 秒才就绪 | 嵌入式 Neo4j 初始化 | 正常现象，等待 `LOCAL_NEO4J_READY` |
| 关闭控制台后查询失败 | 本地服务随控制台退出 | 重新双击 `start_neo4j.bat` |
| `7474` 打不开 | 本地嵌入式模式没有 Browser | 用 Streamlit；Docker 模式才有 Browser |
| 想清空图谱 | 需要重置数据目录 | 见上面的“重置图谱” |
| 换机器 | `.runtime`、`venv` 是可重建的 | 重新执行 `install_python.bat`，并按 local_neo4j/README 重建运行时 |
| 仍想用 Docker | 当前机器安装失败 | `docker-compose.yml` 保留，可在其他机器使用 |

---

## 10. 安全与边界

- 本地 Neo4j 只绑定 `127.0.0.1`，认证关闭仅适用于单用户本机演示；
- Docker 方案保留认证配置；生产环境应使用 Neo4j Server / AuraDB 并启用 TLS；
- 未修改系统 PATH、注册表或全局 Java/Python 包目录；
- 未联网下载业务数据；所有业务 CSV 均为项目内手写模拟数据；
- Docker Desktop 和 JDK/Maven 的下载只发生在工作区；Docker 当前未安装。

完整技术说明见 [EnterpriseKG/README.md](EnterpriseKG/README.md)。
