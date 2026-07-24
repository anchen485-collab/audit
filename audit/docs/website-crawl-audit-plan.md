# Plan: 官网定向爬取审计方案

**Generated**: 2026-07-21  
**Estimated Complexity**: Medium  
**目标**: 暂停企查查 API 后，改用员工 Excel 中企业官网超链接，定向爬取“公司简介、经典案例、业务领域”三个模块，为分类审计提供外部证据。

## Overview

当前审计 Agent 已经具备 Excel 上传、内部分类表解析、LangGraph 编排、规则匹配和结果 Excel 导出能力。新方案不再依赖企查查经营范围，而是从员工录入 Excel 的“企业名称&官网”单元格中读取官网超链接，访问官网并只提取三个高价值模块：

- 公司简介
- 经典案例
- 业务领域

爬取到的正文文本会作为 `CompanyInfo.business_scope` 的替代证据文本，继续复用现有规则匹配能力。第一版只做轻量、定向、可控爬取，不做全站深爬，不爬图片、视频、PDF、附件，不处理登录后的内容。

## Prerequisites

- Excel 中“企业名称&官网”列必须存在真实单元格超链接，即 `cell.hyperlink.target` 可读取。
- 只爬取公开官网页面，遵守合理访问频率。
- 第一版使用 `requests + BeautifulSoup` 解析静态 HTML。
- 若官网为强动态渲染页面，第一版标记为“官网证据不足”，后续再考虑 Playwright 兜底。
- `.env` 中新增官网爬取配置。

## Suggested Configuration

```text
COMPANY_PROVIDER=website
WEBSITE_CRAWL_MAX_PAGES=4
WEBSITE_CRAWL_TIMEOUT=8
WEBSITE_CRAWL_TARGET_MODULES=公司简介,经典案例,业务领域
WEBSITE_CRAWL_CONCURRENCY=5
```

## Sprint 1: Excel 超链接读取

**Goal**: 从员工录入 Excel 中读取企业名称和官网 URL。

**Demo/Validation**:
- 上传带超链接的员工 Excel。
- 系统可以在审计明细中输出官网链接。

### Task 1.1: 扩展 EmployeeRecord

- **Location**: `app/core/models.py`
- **Description**: 为 `EmployeeRecord` 增加 `website_url` 字段，默认空字符串。
- **Dependencies**: None
- **Acceptance Criteria**:
  - 不影响已有测试和已有 Excel 读取逻辑。
  - 无超链接时字段为空。
- **Validation**:
  - `python -m pytest tests/test_excel_reader.py`

### Task 1.2: 读取企业官网超链接

- **Location**: `app/excel/input_reader.py`
- **Description**: 读取“企业名称&官网”列单元格的 `hyperlink.target`。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - 单元格有超链接时写入 `website_url`。
  - 没有超链接时不报错。
  - 保留企业名称原文。
- **Validation**:
  - 新增测试：构造含超链接的 Excel，断言 `website_url` 正确。

## Sprint 2: 官网定向爬取模块

**Goal**: 只抓取官网首页以及与“公司简介、经典案例、业务领域”相关的页面。

**Demo/Validation**:
- 输入官网 URL，输出清洗后的文本证据。
- 最多抓取配置限制内的页面。

### Task 2.1: 新增 WebsiteCrawler

- **Location**: `app/company/website_crawler.py`
- **Description**: 封装网页请求、链接提取、正文清洗。
- **Dependencies**: None
- **Acceptance Criteria**:
  - 支持超时配置。
  - 只访问同域名链接。
  - 忽略图片、PDF、视频、压缩包等附件链接。
  - 首页文本不足时，再抓取目标模块链接。
- **Validation**:
  - 使用 fake HTTP 响应测试链接筛选和文本提取。

### Task 2.2: 目标模块链接筛选

- **Location**: `app/company/website_crawler.py`
- **Description**: 从首页链接中筛选包含目标模块关键词的链接。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - 只匹配“公司简介、经典案例、业务领域”及同义词。
  - 每家公司总页面数不超过 `WEBSITE_CRAWL_MAX_PAGES`。
  - 去重并保持优先级：业务领域 > 公司简介 > 经典案例 > 首页。
- **Validation**:
  - 单元测试覆盖中文链接、相对链接、重复链接、外域链接。

### Task 2.3: 正文清洗

- **Location**: `app/company/website_crawler.py`
- **Description**: 去除脚本、样式、导航、页脚等低价值文本，保留主体文本。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - 删除 `script/style/nav/footer`。
  - 连续空白合并。
  - 单家公司最多保留配置长度内的文本。
- **Validation**:
  - 单元测试覆盖 HTML 清洗。

## Sprint 3: WebsiteCompanyInfoProvider

**Goal**: 用官网爬取结果替代企查查经营范围，接入现有审计流程。

**Demo/Validation**:
- 设置 `COMPANY_PROVIDER=website` 后，上传 Excel 可以用官网文本完成判断。

### Task 3.1: 新增 WebsiteCompanyInfoProvider

- **Location**: `app/company/website_provider.py`
- **Description**: 根据 `EmployeeRecord.website_url` 抓取官网文本，并返回 `CompanyInfo`。
- **Dependencies**: Sprint 1, Sprint 2
- **Acceptance Criteria**:
  - 成功时 `source=website`。
  - `business_scope` 存放官网证据文本。
  - 官网无法访问时返回 `success=False` 和明确错误原因。
- **Validation**:
  - 单元测试覆盖成功、无 URL、无法访问、文本不足。

### Task 3.2: 调整查询节点支持整条记录

- **Location**: `app/audit/nodes.py`, `app/company/provider.py`
- **Description**: 当前 Provider 只接收公司名称，官网模式需要读取 `website_url`。为 Provider 增加可选 `get_company_info_for_record(record)` 默认实现。
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - mock 和 qichacha 兼容旧逻辑。
  - website provider 可以读取记录中的 URL。
  - LangGraph 查询节点不需要知道具体 Provider 类型。
- **Validation**:
  - `python -m pytest tests/test_graph.py`

### Task 3.3: Provider 工厂接入 website 模式

- **Location**: `app/company/factory.py`
- **Description**: 支持 `COMPANY_PROVIDER=website`。
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - `.env` 设置为 website 时返回 WebsiteCompanyInfoProvider。
  - 保留 mock/qichacha 模式。
- **Validation**:
  - `python -m pytest tests/test_company_factory.py`

## Sprint 4: 审计结果展示优化

**Goal**: 让导出的 Excel 能说明数据来自官网，而不是误导为工商经营范围。

**Demo/Validation**:
- 导出 Excel 中能看到官网链接、数据来源、证据文本。

### Task 4.1: 扩展 AuditResult 字段

- **Location**: `app/core/models.py`, `app/audit/rules.py`
- **Description**: 增加 `data_source`、`website_url` 或复用现有字段时明确写入来源。
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - 官网模式下导出数据来源为“官网”。
  - 无官网或证据不足时错误原因清晰。
- **Validation**:
  - 单元测试覆盖官网证据不足。

### Task 4.2: 调整导出列名

- **Location**: `app/excel/result_writer.py`
- **Description**: 将“经营范围”调整为更中性的“外部证据文本”，新增“官网链接/数据来源”。
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - qichacha/mock/website 三种来源都能正常导出。
  - 旧测试更新后通过。
- **Validation**:
  - `python -m pytest tests/test_graph.py tests/test_api_upload.py`

## Sprint 5: 性能与稳定性

**Goal**: 控制爬取耗时，避免批量审计卡死。

**Demo/Validation**:
- 批量处理 20 家官网时不会无限等待。

### Task 5.1: 官网缓存

- **Location**: `app/company/cache.py`
- **Description**: 缓存官网 URL 的抓取结果，避免重复访问。
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - 同一官网 URL 重复出现时只抓一次。
  - 缓存包含抓取时间、URL、证据文本、错误原因。
- **Validation**:
  - 单元测试确认重复 URL 只请求一次。

### Task 5.2: 并发控制

- **Location**: `app/audit/nodes.py`
- **Description**: 第一版可以先串行；若耗时较长，再使用线程池并发抓取，默认并发 5。
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - 并发数可配置。
  - 单个失败不影响其他企业。
- **Validation**:
  - 手动测试 20 条数据的耗时。

## Testing Strategy

- Excel 超链接读取测试。
- 官网链接筛选测试。
- HTML 正文清洗测试。
- WebsiteCompanyInfoProvider 成功/失败测试。
- Provider 工厂 website 模式测试。
- LangGraph 集成测试。
- API 上传下载测试。

## Potential Risks & Gotchas

- 官网可能没有超链接：输出“官网链接缺失”。
- 官网打不开或证书异常：输出“官网无法访问”。
- 官网是动态渲染：第一版输出“官网证据不足”，后续 Playwright 兜底。
- 官网文本很泛：输出“疑似错误/无法判断”，不强行判错。
- 网站结构不统一：只依赖关键词筛选，不绑定固定页面路径。
- 爬取耗时：通过最大页数、超时、缓存、并发控制。

## Rollback Plan

- 保留 `mock` 和 `qichacha` Provider。
- 如果官网爬取效果不稳定，只需要把 `.env` 的 `COMPANY_PROVIDER` 改回 `mock` 或 `qichacha`。
- 规则匹配层不推倒重写，官网文本只是替代外部证据来源。
