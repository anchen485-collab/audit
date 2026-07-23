# Plan: 官网证据包含式审计判定

**Generated**: 2026-07-22
**Estimated Complexity**: Medium

## Overview
当前审计 Agent 已能从企业官网爬取证据，但规则判定仍主要依赖累计分数。新需求是：当官网证据文本已经包含员工录入的二级或三级分类名称时，不应直接判错；即使官网证据还体现了其他业务方向，也应判为“正确”，同时在结果原因中提示“官网证据范围较宽，建议补充/人工确认”。

本次调整只修改审计判定层，不改官网爬虫、Excel 读取和导出结构。

## Prerequisites
- 项目路径：`D:\audit`
- 运行环境可执行 `python -m pytest`
- 员工录入表字段保持不变：`一级分类`、`细分`
- 内部分类表字段保持不变：`一级品类`、`二级品类`、`三级品类`、`模块名称`、`子模块列表`

## Sprint 1: 定位与测试固化
**Goal**: 用测试固定新业务规则，避免后续调整误伤。
**Demo/Validation**:
- 新增测试在当前实现下失败。
- 失败原因指向审计状态不是“正确”。

### Task 1.1: 增加包含式证据命中测试
- **Location**: `D:\audit\tests\test_rules.py`
- **Description**: 构造“电力 / 发电工程”录入记录，官网证据同时包含“发电工程”和“输变电工程”。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 结果状态应为“正确”。
  - `needs_review` 应为 `True`。
  - `error_type` 应提示补充信息或证据范围较宽。
  - 不给出错误修正建议。
- **Validation**: `python -m pytest tests/test_rules.py`

## Sprint 2: 规则判定调整
**Goal**: 在规则评分不足但证据直接包含录入分类时，优先判为正确并提示信息不足。
**Demo/Validation**:
- Sprint 1 的新增测试通过。
- 原有“明显错分推荐更优分类”的测试仍通过。

### Task 2.1: 增加录入分类证据包含判断
- **Location**: `D:\audit\app\audit\rules.py`
- **Description**: 新增一个小函数判断官网证据是否直接包含员工录入的一级分类或细分名称。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - 证据文本包含 `record.category` 或 `record.subcategory` 时返回命中项。
  - 空值不参与命中。
- **Validation**: `python -m pytest tests/test_rules.py`

### Task 2.2: 在错误分支前应用包含式正确判定
- **Location**: `D:\audit\app\audit\rules.py`
- **Description**: 在“推荐分类更优则判错”之前，如果当前分类组合存在且官网证据包含录入分类名称，则判为“正确”，但 `needs_review=True` 并写明提示原因。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - 包含式命中不会进入“细分错误”分支。
  - 结果中不填 `suggestion`。
  - 置信度至少达到人工可接受的中高置信值。
- **Validation**: `python -m pytest tests/test_rules.py`

## Sprint 3: 回归验证
**Goal**: 确保新规则不会破坏已有审计行为。
**Demo/Validation**:
- 全量测试通过。
- Git diff 只包含计划文档、规则代码和测试。

### Task 3.1: 运行相关和全量测试
- **Location**: `D:\audit`
- **Description**: 先跑规则测试，再跑全量测试。
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - `python -m pytest tests/test_rules.py` 通过。
  - `python -m pytest` 通过。
- **Validation**: 查看 pytest 输出。

## Testing Strategy
- 单元测试覆盖“官网证据包含当前录入分类但同时包含其他分类”的核心场景。
- 保留已有错分测试，验证真正更匹配其他分类时仍可判错。
- 全量测试覆盖 Excel、爬虫、缓存、日志和 LangGraph 流程回归。

## Potential Risks & Gotchas
- 如果官网证据只是导航菜单或无关文字中出现分类名称，可能造成误判正确；因此本版只作为 v1.0 规则优化，后续可结合证据段落位置、关键词密度和页面模块来源继续增强。
- 当前员工表只有 `一级分类` 和 `细分` 两列，代码实际把它们映射到内部分类表的二级、三级组合；本次不调整字段语义，避免影响已有模板。
- “判对但提示缺少信息”会让结果状态计入正确数量，但 `是否需要人工复核` 为“是”，业务上需要接受这种统计口径。

## Rollback Plan
- 删除本次新增测试。
- 移除 `rules.py` 中的包含式命中函数和对应判定分支。
- 恢复为仅按分数阈值判断正确、错误、疑似错误。
