# Plan: 细分字段兼容二级/三级分类

**Generated**: 2026-07-22
**Estimated Complexity**: Medium

## Overview
用户上传的员工录入 Excel 中，`一级分类` 是固定列；`细分` 列可能填写内部分类表的二级分类，也可能填写三级分类。当前审计规则默认用 `(内部二级 == 一级分类) + (内部三级 == 细分)` 判断当前录入分类是否存在，无法覆盖 `细分=二级分类` 的情况。

本次目标是让审计 Agent 同时兼容：

- 新语义：员工 `一级分类` 对应内部 `一级品类`，员工 `细分` 可以是内部 `二级品类` 或 `三级品类`。
- 旧兼容：历史测试和旧数据中，员工 `一级分类` 可能对应内部 `二级品类`，员工 `细分` 对应内部 `三级品类`。

## Prerequisites
- 项目路径：`D:\audit`
- 当前分类表 JSON 索引已可从 Excel 生成。
- 运行测试命令：`python -m pytest`

## Sprint 1: 测试固化
**Goal**: 用测试明确 `细分=二级` 和 `细分=三级` 都可以判定为当前录入分类存在。
**Demo/Validation**:
- 新增规则测试在当前实现下失败。
- 失败原因指向当前分类组合没有被识别。

### Task 1.1: 增加 `细分=二级分类` 测试
- **Location**: `D:\audit\tests\test_rules.py`
- **Description**: 构造 `一级分类=种植业`、`细分=蔬菜作物`，内部分类表存在 `种植业 / 蔬菜作物 / 叶菜类`。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 官网证据包含 `蔬菜作物` 或蔬菜相关关键词时，不判为内部分类不存在或细分错误。
  - 状态为 `正确` 或 `正确但需补充信息`。
- **Validation**: `python -m pytest tests/test_rules.py`

### Task 1.2: 增加 `细分=三级分类` 测试
- **Location**: `D:\audit\tests\test_rules.py`
- **Description**: 构造 `一级分类=种植业`、`细分=叶菜类`，内部分类表存在 `种植业 / 蔬菜作物 / 叶菜类`。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 命中三级时可判为当前录入分类存在。
  - 不因为 `细分` 不是二级而判错。
- **Validation**: `python -m pytest tests/test_rules.py`

### Task 1.3: 增加 LLM 提示兼容测试
- **Location**: `D:\audit\tests\test_classification_agent.py`
- **Description**: 校验 prompt 明确告诉模型：员工 `细分` 可能是二级或三级，不要固定按二级解释。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - prompt 包含 `细分可能是二级或三级` 的描述。
  - JSON 输出字段允许返回 `matched_level3`。
- **Validation**: `python -m pytest tests/test_classification_agent.py`

## Sprint 2: 分类路径匹配改造
**Goal**: 把“当前录入分类是否存在”和“当前录入分类得分”从单个 key 改为多候选匹配。
**Demo/Validation**:
- `细分=二级` 时，可以匹配该二级下任意三级规则组。
- `细分=三级` 时，可以匹配具体三级规则组。

### Task 2.1: 新增分类路径匹配函数
- **Location**: `D:\audit\app\audit\rules.py`
- **Description**: 新增 `_matches_entered_category_path(key, record)`，统一判断分类路径是否匹配当前录入。
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - 支持 `key[0] == record.category and key[1] == record.subcategory`。
  - 支持 `key[0] == record.category and key[2] == record.subcategory`。
  - 保留旧兼容：`key[1] == record.category and key[2] == record.subcategory`。
- **Validation**: `python -m pytest tests/test_rules.py`

### Task 2.2: 当前分类分数取多候选最高分
- **Location**: `D:\audit\app\audit\rules.py`
- **Description**: 遍历规则组时，如果多个 key 都匹配当前录入，选择分数最高的一组作为当前结果依据。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - `current_key` 不再只看固定 `(二级, 三级)`。
  - 推荐分类不会把当前二级下的三级候选误判为错误。
- **Validation**: `python -m pytest tests/test_rules.py`

## Sprint 3: LLM 提示和 agent 结果校验
**Goal**: 大模型 Agent 也理解 `细分` 字段的不稳定语义。
**Demo/Validation**:
- prompt 不再写死“当前二级分类”。
- agent 返回正确时，内部分类存在校验支持二级/三级。

### Task 3.1: 调整 prompt 文案
- **Location**: `D:\audit\app\agent\classification_agent.py`
- **Description**: 把系统提示和用户提示改成“判断员工一级分类和细分是否合理；细分可能是二级或三级”。
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - 输出 JSON 保留 `matched_level1`、`matched_level2`、`matched_level3`。
  - 建议修正可输出 `一级 / 二级` 或 `一级 / 二级 / 三级`。
- **Validation**: `python -m pytest tests/test_classification_agent.py`

### Task 3.2: 调整 agent 正确结果校验
- **Location**: `D:\audit\app\audit\rules.py`
- **Description**: `_apply_agent_result` 判断员工录入分类是否存在时，使用新的路径匹配函数。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - agent 返回正确时，如果员工 `细分` 是内部二级或三级，都可通过存在性校验。
  - 不再只检查一级/二级组合。
- **Validation**: `python -m pytest tests/test_rules.py tests/test_classification_agent.py`

## Testing Strategy
- 单元测试覆盖 `细分=二级`、`细分=三级`、旧兼容路径。
- LLM prompt 测试覆盖提示内容和返回字段。
- 全量测试确保 Excel、JSON 规则索引、Web 上传和官网爬取链路不受影响。

## Potential Risks & Gotchas
- 如果 `细分` 命中二级分类，一个二级下可能有多个三级规则组，需要选择证据分数最高的组作为当前结果。
- 如果二级和三级存在同名，可能出现多个匹配候选；本版用最高分解决，后续可在结果原因中展示更多候选。
- 旧数据可能把员工 `一级分类` 填成内部二级，本次保留兼容，但后续最好统一模板字段含义。
- LLM Agent 如果启用，原 prompt 写死二级分类，需要同步调整，否则规则层和语义层会产生不一致。

## Rollback Plan
- 恢复 `audit_record` 中固定 `key[1] == record.category and key[2] == record.subcategory` 的判断。
- 恢复 LLM prompt 中“只判断一级和二级”的描述。
- 删除新增兼容测试。
