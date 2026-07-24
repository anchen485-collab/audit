# Plan: 官网有限深度爬取

**Generated**: 2026-07-21
**Estimated Complexity**: Medium

## Overview

当前官网爬虫只从首页抓取直达的“公司简介、经典案例、业务领域”链接。新需求是支持目标页面藏在二级或三级栏目中的情况，例如：

```text
首页 -> 关于我们 -> 公司简介
首页 -> 解决方案 -> 农业方案 -> 业务领域
首页 -> 案例中心 -> 经典案例
```

实现方式是有限深度爬取：从首页开始，只沿同域名、非附件、与目标栏目或候选栏目相关的链接继续探索。最大深度和最大页面数都可配置，避免变成全站深爬。

## Prerequisites

- 继续使用 `requests + BeautifulSoup`。
- 只访问同域名公开页面。
- 默认最大深度为 `2`，可通过 `.env` 调整。
- 保留最大页数、超时、缓存控制。

## Sprint 1: 深度参数

### Task 1.1: 增加 max_depth 配置

- **Location**: `app/company/website_crawler.py`, `app/company/factory.py`
- **Description**: `WebsiteCrawler` 增加 `max_depth`，工厂从 `.env` 读取 `WEBSITE_CRAWL_MAX_DEPTH`。
- **Acceptance Criteria**:
  - 默认深度为 `2`。
  - `.env` 可以覆盖深度。
- **Validation**:
  - `python -m pytest tests/test_company_factory.py`

## Sprint 2: 有限深度链接发现

### Task 2.1: 支持二级/三级目标链接

- **Location**: `app/company/website_crawler.py`
- **Description**: 从首页开始 BFS 探索，候选栏目页也可以继续提取目标链接。
- **Acceptance Criteria**:
  - 能抓到二级页面中的“公司简介”。
  - 能抓到三级页面中的“业务领域”。
  - 不访问外域链接。
  - 不超过最大深度和最大页面数。
- **Validation**:
  - 新增 `tests/test_website_crawler_depth.py`。

### Task 2.2: 候选栏目关键词

- **Location**: `app/company/website_crawler.py`
- **Description**: 允许沿着“关于、简介、公司、业务、领域、案例、方案、产品、服务、项目”等中间栏目继续探索。
- **Acceptance Criteria**:
  - 中间栏目用于发现，不一定作为证据页。
  - 目标模块页面仍优先进入证据文本。
- **Validation**:
  - 单元测试覆盖中间栏目。

## Sprint 3: 文档和验证

### Task 3.1: README 增加深度配置

- **Location**: `README.md`
- **Description**: 补充 `WEBSITE_CRAWL_MAX_DEPTH` 的作用和建议值。
- **Acceptance Criteria**:
  - 说明默认值和调大后的耗时风险。
- **Validation**:
  - 人工检查 README。

## Testing Strategy

- 单元测试覆盖二级和三级目标页面。
- 单元测试覆盖最大深度限制。
- 全量测试确认原有审计流程不受影响。

## Potential Risks & Gotchas

- 深度越大越慢，第一版建议不超过 `3`。
- 中间栏目文字可能较多，证据文本优先保留目标模块页面。
- 动态菜单仍可能抓不到，后续可考虑 Playwright。

## Rollback Plan

将 `WEBSITE_CRAWL_MAX_DEPTH=1` 即可退回只抓首页直达目标页的行为。
