# Plan: JSON 规则索引优化

**Generated**: 2026-07-22
**Estimated Complexity**: Medium

## Overview
当前审计 Agent 每次运行都需要上传员工录入 Excel 和内部分类表 Excel。内部分类表是固定规则资产，重复上传会增加使用成本，也会导致不同批次使用不同版本规则。优化目标是把内部分类表 Excel 转换为服务端固定 JSON 规则索引，审计时直接加载 JSON 对象和关键词倒排索引。

本次采用“Excel 作为业务维护源，JSON 作为运行时规则库”的方案。Web 页面只上传员工录入表；分类规则通过环境变量指定 JSON 路径。底层工作流保留读取 Excel 分类表的兼容能力，方便测试和临时迁移。

## Prerequisites
- 项目路径：`D:\audit`
- 分类表源文件结构保持：`一级品类`、`二级品类`、`三级品类`、`模块名称`、`子模块列表`
- 已安装 `openpyxl`
- 运行验证命令：`python -m pytest`

## Sprint 1: JSON 索引格式与测试
**Goal**: 固化 JSON 规则库的数据结构，保证 Excel 转 JSON 后仍能还原为现有 `CategoryRule`。
**Demo/Validation**:
- 构造一个小型分类表 Excel。
- 生成 JSON。
- 从 JSON 读取出规则和关键词索引。

### Task 1.1: 新增 JSON 索引测试
- **Location**: `D:\audit\tests\test_category_rule_index.py`
- **Description**: 测试 Excel 转 JSON、JSON 加载、关键词倒排索引生成。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - JSON 中包含 `version`、`rules`、`category_tree`、`keyword_index`。
  - `load_category_rules_from_json` 能还原为 `CategoryRule` 列表。
  - 关键词 `蔬菜` 能映射到对应分类路径。
- **Validation**: `python -m pytest tests/test_category_rule_index.py`

## Sprint 2: 规则索引实现
**Goal**: 增加可复用的规则索引模块。
**Demo/Validation**:
- 可通过函数把 Excel 转为 JSON 文件。
- 可通过函数读取 JSON 文件并返回规则列表。

### Task 2.1: 实现规则索引模块
- **Location**: `D:\audit\app\category\rule_index.py`
- **Description**: 新增 Excel 转 JSON、JSON 读写、关键词索引构建函数。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - 使用现有 `read_category_rules` 解析 Excel，避免重复造解析逻辑。
  - 忽略空关键词。
  - 为通用模块保留数据，但关键词索引中标注较低权重。
- **Validation**: `python -m pytest tests/test_category_rule_index.py`

### Task 2.2: 增加配置读取
- **Location**: `D:\audit\app\core\config.py`
- **Description**: 增加 `CATEGORY_RULES_JSON_PATH`、`CATEGORY_RULES_EXCEL_PATH` 的读取函数。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - JSON 路径默认指向 `storage/category_rules.json`。
  - 如果 JSON 缺失且 Excel 路径存在，可从 Excel 自动生成 JSON。
- **Validation**: 单元测试和工作流测试。

## Sprint 3: 工作流与 Web 入口改造
**Goal**: 审计流程默认使用固定 JSON 规则库，不再要求用户上传分类表。
**Demo/Validation**:
- 首页只有员工录入 Excel 上传控件。
- 上传员工表后能完成审计并导出结果。

### Task 3.1: 改造 `read_category_node`
- **Location**: `D:\audit\app\audit\nodes.py`
- **Description**: 当状态中没有分类表路径时，从配置的 JSON 规则库加载规则。
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - 旧路径传入 Excel 时仍可读取 Excel。
  - 新路径未传分类表时使用 JSON。
- **Validation**: `python -m pytest tests/test_graph.py`

### Task 3.2: 改造 FastAPI 上传接口
- **Location**: `D:\audit\app\main.py`、`D:\audit\app\web\templates\index.html`
- **Description**: 移除 `category_file` 上传字段，只保存员工录入表。
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - `/audit/upload` 只接收 `employee_file`。
  - 日志中显示使用服务端分类规则。
  - 分类规则缺失时返回清晰错误页。
- **Validation**: `python -m pytest tests/test_api_upload.py`

## Sprint 4: 文档与回归验证
**Goal**: 让本地运行、规则更新、问题排查流程清楚可执行。
**Demo/Validation**:
- `.env.example` 有新配置。
- README 有生成 JSON 规则库说明。
- 全量测试通过。

### Task 4.1: 补充配置示例和 README
- **Location**: `D:\audit\.env.example`、`D:\audit\README.md`
- **Description**: 说明如何配置分类表 Excel 源和 JSON 规则文件。
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - 用户知道首次运行前如何生成或配置规则库。
  - 说明真实分类表数据不要提交到 GitHub。
- **Validation**: 人工检查文档。

### Task 4.2: 全量测试
- **Location**: `D:\audit`
- **Description**: 跑完整测试套件。
- **Dependencies**: Sprint 4.1
- **Acceptance Criteria**:
  - `python -m pytest` 通过。
- **Validation**: 查看测试输出。

## Testing Strategy
- 单元测试：JSON 索引生成、加载、关键词索引。
- 集成测试：LangGraph 工作流从 JSON 规则库读取分类。
- API 测试：Web 上传入口只传员工 Excel。
- 回归测试：现有 Excel 分类读取和规则匹配继续通过。

## Potential Risks & Gotchas
- 真实分类表是内部资产，生成的 JSON 同样可能包含敏感业务规则，不建议提交到 GitHub。
- 分类表中 `环节`、`生态` 有大量通用词，索引可保留，但匹配评分不能把这些词当成强证据。
- 如果 JSON 文件缺失且没有配置 Excel 源文件，系统需要给出清晰错误，而不是静默无法判断。
- 旧测试或脚本可能仍传入分类 Excel 路径，本次保留兼容以降低迁移风险。

## Rollback Plan
- Web 入口恢复 `category_file` 上传字段。
- `run_audit_workflow` 恢复强制分类表参数。
- `read_category_node` 恢复只读取 Excel。
- 删除 `app/category/rule_index.py` 和相关测试。
