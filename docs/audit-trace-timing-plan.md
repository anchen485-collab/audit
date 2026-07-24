# Plan: 审计 Agent 阶段耗时 Trace

**Generated**: 2026-07-22
**Estimated Complexity**: Medium

## Overview
当前审计 Agent 已有关键日志，但缺少统一 trace_id、阶段耗时、单企业耗时和慢步骤定位。第一版 trace 目标是在不引入新监控系统的前提下，通过结构化日志和最终状态中的 `trace` 字段，定位一次审计任务中 Excel 读取、分类规则加载、企业官网抓取、规则匹配、汇总、导出等阶段的耗时。

## Prerequisites
- 保持现有 FastAPI、LangGraph、pytest 技术栈不变。
- 不额外引入数据库或 APM，先使用 Python 标准库 `time.perf_counter()`。
- trace 日志需要出现在控制台，字段尽量结构化，便于后续复制到 Excel 或日志系统分析。

## Sprint 1: Trace 数据结构与工具函数
**Goal**: 提供统一的计时能力，避免每个节点手写重复逻辑。
**Demo/Validation**:
- 单元测试能验证计时器会返回 `duration_ms`。
- 日志中包含 `trace_id`、`stage`、`duration_ms`。

### Task 1.1: 扩展 AuditGraphState
- **Location**: `D:\audit\app\core\models.py`
- **Description**: 增加 `trace_id`、`trace` 字段；`trace` 保存阶段耗时列表。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - LangGraph state 可以传递 trace 信息。
  - 不影响现有字段。
- **Validation**:
  - 更新/新增 graph 测试，断言最终 state 中存在 trace。

### Task 1.2: 新增 trace 工具模块
- **Location**: `D:\audit\app\core\trace.py`
- **Description**: 新增 `record_stage_timing()` 或上下文管理器，用于记录开始、结束、耗时和状态。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - 成功和异常场景都能记录耗时。
  - 使用中文注释解释关键逻辑。
- **Validation**:
  - 新增 `D:\audit\tests\test_trace.py`。

## Sprint 2: LangGraph 节点级耗时
**Goal**: 每个审计节点都有可读耗时。
**Demo/Validation**:
- 控制台能看到 `audit_trace_stage_done` 日志。
- 最终 state 返回所有节点耗时。

### Task 2.1: 包装 6 个审计节点
- **Location**: `D:\audit\app\audit\graph.py`, `D:\audit\app\audit\nodes.py`
- **Description**: 对 `read_employee`、`read_category`、`query_company`、`match_rules`、`build_summary`、`export_result` 记录耗时。
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - 每个阶段都有 `stage`、`duration_ms`、`status`。
  - `audit_workflow_done` 包含 `total_duration_ms`。
- **Validation**:
  - 更新 `D:\audit\tests\test_logging.py`，断言 trace 日志出现。
  - 更新 `D:\audit\tests\test_graph.py`，断言 trace 阶段数量。

### Task 2.2: 审计入口记录总耗时
- **Location**: `D:\audit\app\audit\graph.py`, `D:\audit\app\main.py`
- **Description**: 生成 `trace_id`，贯穿整个 workflow；上传接口日志输出总耗时。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - 同一次任务所有日志使用同一个 `trace_id`。
  - API 上传完成日志能看到 `duration_ms`。
- **Validation**:
  - API upload 测试仍通过。

## Sprint 3: 慢点细分 Trace
**Goal**: 如果总耗时长，可以定位是某个企业、某个网页、清洗还是 LLM 慢。
**Demo/Validation**:
- 控制台能看到单企业查询耗时和官网每页抓取耗时。

### Task 3.1: 企业查询耗时
- **Location**: `D:\audit\app\audit\nodes.py`
- **Description**: 在 `query_company_node` 内记录每个去重企业的查询耗时。
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - 日志包含 `company`、`row`、`provider`、`duration_ms`、`success`。
- **Validation**:
  - `D:\audit\tests\test_logging.py` 增加断言。

### Task 3.2: 官网爬虫页级耗时
- **Location**: `D:\audit\app\company\website_crawler.py`, `D:\audit\app\company\website_provider.py`
- **Description**: 记录单次官网爬取总耗时、每个 URL 访问耗时、候选链接数量。
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - 日志能区分 `website_crawl_page_done` 与 `website_crawl_done`。
  - 缓存命中日志也记录耗时为 0 或近似 0。
- **Validation**:
  - 官网爬虫测试仍通过，日志测试新增耗时字段断言。

### Task 3.3: LLM 分类耗时
- **Location**: `D:\audit\app\agent\classification_agent.py`, `D:\audit\app\audit\rules.py`
- **Description**: 大模型启用时记录单条调用耗时、模型名、结果状态。
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - 不打印 API Key。
  - LLM 超时和 JSON 解析失败也记录耗时。
- **Validation**:
  - 分类 Agent 测试仍通过。

## Sprint 4: 输出与文档
**Goal**: 让用户知道怎么读 trace，怎么判断慢点。
**Demo/Validation**:
- README 有 trace 字段说明。

### Task 4.1: README 增加 trace 使用说明
- **Location**: `D:\audit\README.md`
- **Description**: 写明控制台日志关键词、常见慢点解释、推荐配置。
- **Dependencies**: Sprint 1-3
- **Acceptance Criteria**:
  - 用户能通过搜索 `audit_trace`、`website_crawl_page_done` 定位耗时。
- **Validation**:
  - 文档内容可读，无敏感信息。

## Testing Strategy
- 先写失败测试，再改实现。
- 最小测试集：
  - `python -m pytest tests\test_trace.py tests\test_logging.py tests\test_graph.py -q`
  - `python -m pytest tests\test_website_crawler.py tests\test_website_crawler_depth.py tests\test_website_provider.py -q`
- 最终全量验证：
  - `python -m pytest`

## Potential Risks & Gotchas
- LangGraph 节点返回的是局部 state，trace 追加方式要避免覆盖上游字段。
- 日志中不要输出官网完整大段正文，避免控制台噪声和敏感数据泄露。
- `time.perf_counter()` 只用于耗时，不用于展示真实日期时间。
- 单企业查询如果串行执行，trace 只能定位慢企业，不能降低总耗时；后续可基于 trace 再考虑并发。

## Rollback Plan
- 删除 `app\core\trace.py`。
- 回退 `AuditGraphState` 中新增的 trace 字段。
- 回退审计节点、官网爬虫、LLM Agent 中新增的 trace 日志。
- 保留原有业务逻辑和已有日志不变。
