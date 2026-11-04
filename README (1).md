# EnterpriseKG 技术说明

轻量级企业知识图谱参考实现：4 张模拟 CSV → 标准化 → 实体对齐 → **真实 Neo4j 5.26.32 图数据库** → Streamlit 工作台。
全部代码为 Python，不使用 Notebook；Docker 安装失败后改为工作区便携 Neo4j，无需系统级安装。

---

## 1. 快速运行（Docker-free）

### 1.1 一键顺序

```powershell
# 在 workspace 根目录
.\install_python.bat     # Python/venv/依赖 + 离线自检
.\start_neo4j.bat        # 启动工作区便携 Neo4j（无 Docker）
.\run_pipeline.bat       # 建图 + 质量门禁 + 19 个测试
.\start_app.bat          # http://127.0.0.1:8501
```

首次启动本地 Neo4j 约 30–60 秒；看到 `LOCAL_NEO4J_READY` 后即可执行后续步骤。
使用期间保持 Neo4j 控制台窗口打开；关闭窗口即停止服务，数据仍保存在 `.runtime/neo4j-home`。

### 1.2 模块命令

```powershell
cd EnterpriseKG
.\venv\Scripts\python.exe -m src.graph_builder --reset
.\venv\Scripts\python.exe -m src.quality_check
.\venv\Scripts\python.exe -m src.graph_query --preset duplicates
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m streamlit run app\main.py
```

### 1.3 配置

`config/config.yaml` 定义 CSV 路径、Neo4j URI/用户/密码、rapidfuzz 阈值、数据契约和 UI 属性。
密码优先级：`NEO4J_PASSWORD` 环境变量 > 工作区 `.env` > YAML 默认值。

本地嵌入式模式关闭认证，但只监听 `127.0.0.1`；Python 驱动仍按 `config.yaml` 传入凭据，服务端接受。Docker Server 模式则使用真实认证。

---

## 2. 数据契约

原始数据统一为 **UTF-8、逗号分隔、英文表头**。`data_loader.py` 强制校验必需列，`quality_check.py` 校验行数和主键。

### companies.csv（8 行）

| 列 | 说明 |
|---|---|
| `company_id` | 主键，C001–C008 |
| `name` | 企业名称 |
| `credit_code` | 统一社会信用代码；C008 故意为空 |
| `legal_representative` | 法定代表人 |
| `registered_capital` | 注册资本（万元） |
| `established_date` | 成立日期 |
| `region_code` | 关联 regions |
| `industry` / `status` | 行业 / 状态 |
| `old_name` | 登记曾用名，用于强别名对齐 |

刻意设计的样例：

| 样例 | 数据表现 | 预期处理 |
|---|---|---|
| C001 / C002 | 名称相近，代码不同 | 禁止合并，进入复核 |
| C003 / C004 | 名称相近，代码不同 | 禁止合并，进入复核 |
| C005 / C006 | 代码相同，名称不同 | 自动归并，C006 成为别名 |
| C008 | 代码为空 | 不伪造代码，最高 review |

### 其他表

- `shareholders.csv`：10 条，自然人 + 企业股东，生成 `HOLDS_SHARES`；
- `patents.csv`：8 条，P003/P007 使用曾用名，P005 使用同码名称变体，P008 对应缺代码企业；
- `regions.csv`：3 条，北京海淀 / 苏州工业园区 / 深圳南山。

---

## 3. 模块与执行流

```text
data_loader.load_all
   └─ 读取 + 必需列/空表/主键校验
data_cleaner.clean_all
   └─ NFKC、代码清洗、日期/金额/比例、质量标记
entity_extractor.extract_entities
   └─ Company / Person / ExternalOrganization / Patent / Region
   └─ mentions（专利申请人、持股目标、机构股东）
entity_matcher.match_entities
   └─ 同代码归并 + 曾用名 + 精确名 + rapidfuzz
   └─ 企业两两冲突扫描
   └─ 候选报告 / 复核队列 / 未匹配队列
pipeline.run_pipeline
   └─ 串联并持久化 processed 审计文件
graph_builder.build_graph_seed
   └─ mention 解析 → 节点/关系/候选边
   └─ 写 graph_seed.json + MERGE 到 Neo4j
quality_check
   └─ 11 项本地检查 + Neo4j 在线节点/重复边检查
app/main.py
   └─ 总览 / 对齐审核 / 在线 Cypher / 质量报告
```

### 核心 API

```python
from src.pipeline import run_pipeline
from src.graph_builder import build_graph_seed
from src.quality_check import run_quality_checks

result = run_pipeline(write=True)
seed = build_graph_seed(result["entities"], result["matching"])
report = run_quality_checks(check_neo4j=True)
```

---

## 4. 实体对齐设计

### 4.1 规范化

`normalize_name`：Unicode NFKC、全角括号→半角、删除空白/`·`/`•`、小写化。
`normalize_credit_code`：NFKC、去空格/连字符、转大写，并做 18 位格式校验。

### 4.2 归并顺序

1. **同信用代码聚类**：`company_id` 最小者为 canonical；其余名称写入 `same_code_variant` 别名；C006 → C005。
2. **登记曾用名**：`old_name` → `old_name` 别名，置信度 98；P003/P007 可命中。
3. **精确名称**：唯一命中 → 自动；多个命中 → `ambiguous_name` 人工。
4. **rapidfuzz WRatio**：低于 78 不产生匹配；78–92 复核；≥92 且无硬冲突才自动。

### 4.3 两轴评价

```python
confidence_tier = high | medium | low   # 有多像
decision        = auto_merge | review | keep_separate  # 能不能合
```

| 配置项 | 默认值 | 作用 |
|---|---:|---|
| `auto_merge_threshold` | 92 | 自动合并分数线 |
| `review_threshold` | 78 | 候选/复核最低分 |
| `confidence_high_threshold` | 88 | high 起点 |
| `confidence_medium_threshold` | 78 | medium 起点 |
| `name_weight` | 0.72 | 企业两两比较名称权重 |
| `region_weight` | 0.12 | 地区权重 |
| `industry_weight` | 0.08 | 行业权重 |
| `legal_rep_weight` | 0.08 | 法定代表人权重 |

### 4.4 冲突类型

| `conflicts` | 触发条件 | 处理 |
|---|---|---|
| `different_credit_code` | 两边都有代码且不同 | 硬禁止自动合并 |
| `missing_credit_code` | 任一方代码为空 | 最高 review |
| `ambiguous_name` | 多个 canonical 同名 | 人工消歧 |
| `name_collision` | 名称高度相似且代码不同 | 高风险候选，复核 |
| `same_code_variant` | 同代码不同名 | 自动归并 |
| `registered_old_name` | 命中登记曾用名 | 自动对齐 |

**不做跨代码传递合并**：A≈B、B≈C 不推出 A=C。

---

## 5. 图谱模型

### 节点

| Label | Key | 关键属性 |
|---|---|---|
| `Company` | `company_id` | name, credit_code, normalized_name, aliases[], source_company_ids[], credit_code_missing |
| `CompanyAlias` | `alias_id` | name, alias_type, confidence, method, source_company_id |
| `Person` | `person_id` | name |
| `ExternalOrganization` | `organization_id` | name, credit_code |
| `Patent` | `patent_id` | patent_name, patent_number, applicant_name |
| `Region` | `region_code` | province, city, district |
| `MergeCandidate` | `candidate_id` | score, confidence_tier, decision, conflicts, reasons |

所有节点都有 `project = "EnterpriseKG"`，便于安全清理。

### 关系

```cypher
(:Person|:ExternalOrganization|:Company)-[:HOLDS_SHARES {percentage, amount, date}]->(:Company)
(:Company)-[:OWNS_PATENT {score, method, applicant_name}]->(:Patent)
(:Company)-[:LOCATED_IN]->(:Region)
(:Company)-[:HAS_ALIAS {alias_type, confidence}]->(:CompanyAlias)
(:Company)-[:SUSPECTED_DUPLICATE {score, confidence_tier, decision, conflicts}]->(:Company)
```

### 实测规模

```json
{
  "nodes": {
    "Company": 7,
    "CompanyAlias": 3,
    "Person": 6,
    "ExternalOrganization": 4,
    "Patent": 8,
    "Region": 3,
    "MergeCandidate": 3,
    "total": 34
  },
  "relationships": {
    "HAS_ALIAS": 3,
    "HOLDS_SHARES": 10,
    "LOCATED_IN": 7,
    "OWNS_PATENT": 7,
    "SUSPECTED_DUPLICATE": 3,
    "total": 30
  }
}
```

7 家企业 ≠ 8 条原始记录：C006 归入 C005；C001/C002、C003/C004 仍独立；C008 保留临时企业节点但无代码。

---

## 6. 输出文件

| 文件 | 内容 |
|---|---|
| `data/processed/companies_clean.csv` | 清洗后企业 + `quality_flags` |
| `data/processed/shareholders_clean.csv` | 清洗后股权 |
| `data/processed/patents_clean.csv` | 清洗后专利 |
| `data/processed/regions_clean.csv` | 地区 |
| `data/processed/entities.json` | 实体、mentions、原始关系事实 |
| `data/processed/match_report.json` | canonical 企业、别名、候选对、mention 对齐、统计 |
| `data/processed/match_candidates.csv` | 业务复核候选表 |
| `data/processed/pipeline_meta.json` | 本次运行摘要 |
| `data/output/graph_seed.json` | 图谱节点/关系完整快照 |
| `data/output/graph_build_status.json` | 在线/离线模式、连接状态、节点计数 |
| `data/output/quality_report.json` | 12 项质量检查 + 疑似未合并候选 |

---

## 7. 质量门禁

`python -m src.quality_check` 执行：

1. 四表行数契约（8/10/8/3）；
2. 主键唯一；
3. 信用代码：恰好 1 条缺失、0 条格式非法；
4. 近名不同码的两对关键样例被识别；
5. C006 → C005 同码变体归并；
6. P003/P007 曾用名对齐；
7. P008 缺失代码进入复核；
8. 不存在跨不同代码的自动合并；
9. canonical 企业数量正确；
10. 各企业股权合计不超过 100%；
11. 离线图种子无悬空端点；
12. Neo4j 在线 Company 节点数与疑似重复边数。

实测：**12 PASS / 0 WARN / 0 FAIL**。

---

## 8. 三条核心 Cypher

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

结果：查询 1 返回 7 行；查询 2 返回 3 行；查询 3 返回 12 行。

---

## 9. CLI 参考

```text
python -m src.data_loader        # 只读契约检查
python -m src.data_cleaner       # 生成 processed/*.csv
python -m src.entity_extractor   # 生成 entities.json
python -m src.entity_matcher     # 生成 match_report.json / candidates.csv
python -m src.pipeline           # 全链路，不建图
python -m src.graph_builder --offline
python -m src.graph_builder --reset         # 在线写入
python -m src.graph_builder --require-neo4j # 在线失败退出码 2
python -m src.quality_check
python -m src.quality_check --offline
python -m src.graph_query --list
python -m src.graph_query --preset overview|duplicates|chain|aliases
```

`--reset` 只删除 `project = "EnterpriseKG"` 的节点，不执行全库清空。

---

## 10. Docker-free 本地 Neo4j

| 项目 | 位置/值 |
|---|---|
| 引擎 | Neo4j Community 5.26.32 embedded |
| Bolt | `bolt://127.0.0.1:7687` |
| 数据 | `EnterpriseKG\.runtime\neo4j-home` |
| JRE | `EnterpriseKG\.runtime\jre` |
| JAR | `EnterpriseKG\.runtime\lib` |
| 认证 | 本地嵌入式关闭，仅 loopback |
| 启动 | `start_neo4j_local.bat` / `start_neo4j.bat` |
| 说明 | [local_neo4j/README.md](local_neo4j/README.md) |

本地模式没有 HTTP Browser；使用 Streamlit 或 `graph_query`。Docker 模式仍保留在 `docker-compose.yml`，作为其他机器的可选方案。

---

## 11. 测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

覆盖：数据行数/注入问题、近名不同码、同码归并、曾用名对齐、缺代码复核、跨代码自动合并硬闸门、图谱节点/关系计数、悬空端点、P008 不建专利边、质量门禁无 FAIL。

---

## 12. 已知边界

1. 本地 embedded 模式无 Neo4j Browser，只有 Bolt；UI 由 Streamlit 提供。
2. 本地 embedded 模式关闭认证，仅适合单用户本机；禁止绑定公网。
3. 信用代码仅做 18 位格式校验，未校验 GB 32100 校验位；生产应补充。
4. 企业两两比较是 O(n²)，当前 8 条无压力；上万企业应加 blocking。
5. 未做拼音/简称/跨语言名称对齐。
6. Streamlit 无认证，不要直接暴露公网。
