# 企业录入审计 Agent Version 1.0

这是第一版审计 Agent，用于审计员工录入 Excel 中的企业分类是否合理。

## 当前能力

- 提供简单 Web 页面上传 Excel。
- 支持上传员工录入表，内部分类表使用服务端固定 JSON 规则索引。
- 使用 LangGraph 编排审计流程。
- 使用规则匹配判断录入是否正确。
- 使用 mock 企业经营范围模拟企查查 API。
- 支持 `website` 模式，从企业官网定向爬取“公司简介、经典案例、业务领域”作为外部证据文本。
- 导出审计结果 Excel，包含“审计明细”和“人员汇总”两个 Sheet。

## 第一版边界

- 暂不接入大模型。
- 暂不做登录权限。
- 暂不做人工复核页面。
- 暂不直接调用企查查真实 API。
- 暂不覆盖原始 Excel。

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

## 配置 .env

项目根目录已经提供 `.env` 文件，后续申请到企查查官方 API 后，把下面两个值补进去：

```text
QICHACHA_API_KEY=你的企查查 key
QICHACHA_API_SECRET=你的企查查 secret
QICHACHA_ENDPOINT=https://api.qichacha.com/ECIV4/GetBasicDetailsByName
QICHACHA_SEARCH_PARAM=keyword
QICHACHA_TIMEOUT=15
```

第一版仍然默认使用 mock 数据：

```text
COMPANY_PROVIDER=mock
```

内部分类表不再要求每次上传。推荐让业务人员继续维护 Excel，系统运行时读取 JSON 规则索引：

```text
CATEGORY_RULES_JSON_PATH=storage/category_rules.json
CATEGORY_RULES_EXCEL_PATH=C:/Users/Administrator/Desktop/document/最终分类表.xlsx
```

如果 `CATEGORY_RULES_JSON_PATH` 指向的文件不存在，并且 `CATEGORY_RULES_EXCEL_PATH` 存在，系统会自动从 Excel 生成 JSON。也可以手动生成：

```bash
python scripts/build_category_rules_json.py --excel "C:/Users/Administrator/Desktop/document/最终分类表.xlsx" --json storage/category_rules.json
```

真实分类表和生成后的 `storage/category_rules.json` 都属于内部规则资产，不建议提交到 GitHub。

如果暂停企查查 API，改用官网爬取模式：

```text
COMPANY_PROVIDER=website
AUDIT_LOG_LEVEL=INFO
WEBSITE_CRAWL_MAX_PAGES=8
WEBSITE_CRAWL_MAX_DEPTH=3
WEBSITE_CRAWL_TIMEOUT=8
WEBSITE_CRAWLER_ENGINE=hybrid
WEBSITE_CRAWL_TARGET_MODULES=公司简介,经典案例,业务领域
WEBSITE_CRAWL_CONCURRENCY=5
```

官网模式要求员工录入 Excel 的“企业名称&官网”单元格里存在真实超链接。系统只会读取公开官网页面，并优先抓取：

```text
公司简介
经典案例
业务领域
```

如果目标内容藏在二级或三级栏目里，可以调大深度：

```text
WEBSITE_CRAWL_MAX_DEPTH=3
```

如果路径类似“首页 -> 解决方案 -> 农业方案 -> 业务领域”，需要设置为 `3`。
建议第一版不要超过 `3`，否则批量审计会明显变慢。

官网爬虫默认使用 `hybrid` 模式：先用轻量的 `requests + BeautifulSoup`，如果遇到 JS 渲染官网、HTTP 403 或静态爬虫证据不足，再自动切到 Crawl4AI 兜底：

```text
WEBSITE_CRAWLER_ENGINE=hybrid
```

`crawl4ai` 已包含在 `requirements.txt` 中。启用 `hybrid` 或 `crawl4ai` 前，首次部署环境还需要初始化浏览器依赖：

```bash
crawl4ai-setup
```

可选值：

```text
requests  # 只使用当前轻量爬虫
crawl4ai  # 只使用 Crawl4AI
hybrid    # 默认，轻量爬虫失败后自动切换到 Crawl4AI
```

控制台日志默认使用 `INFO` 级别，会输出上传、读表、企业查询、官网爬取、规则匹配和导出等关键事件。排查问题时可以临时设置：

```text
AUDIT_LOG_LEVEL=INFO
```

## 耗时 Trace 排查

每次审计都会生成一个 `trace_id`，同一次上传、LangGraph 节点执行和最终完成日志会共用这个标识。排查执行时间过长时，优先在控制台搜索：

```text
audit_trace_stage_done
audit_query_company_timing
website_crawl_page_done
website_crawl_done
website_provider_timing
classification_agent_timing
audit_upload_done
```

常见判断方式：

- `audit_trace_stage_done stage=query_company` 慢：通常是官网访问慢、目标网站阻塞或缓存未命中。
- `website_crawl_page_done` 慢：定位具体慢 URL，重点看 `duration_ms`、`depth`、`is_target`。
- `website_crawl_done` 慢：说明单个官网总爬取耗时高，可以降低 `WEBSITE_CRAWL_MAX_PAGES` 或 `WEBSITE_CRAWL_MAX_DEPTH`。
- `audit_trace_stage_done stage=match_rules` 慢：通常是大模型分类 Agent 调用耗时，继续看 `classification_agent_timing`。
- `audit_upload_done` 慢：表示从上传到导出整体耗时高，可用同一 `trace_id` 关联前面的阶段日志。

推荐第一版排查配置：

```text
AUDIT_LOG_LEVEL=INFO
WEBSITE_CRAWL_MAX_PAGES=8
WEBSITE_CRAWL_MAX_DEPTH=3
WEBSITE_CRAWL_TIMEOUT=8
```

## 启动服务

```bash
uvicorn app.main:app --reload
```

启动后打开：

```text
http://127.0.0.1:8000
```

健康检查：

```text
http://127.0.0.1:8000/health
```

## 上传文件要求

员工录入 Excel 表头必须包含：

```text
日期、姓名、一级分类、细分、企业名称&官网
```

其中 `细分` 可以填写内部分类表中的二级品类，也可以填写三级品类；系统会自动兼容这两种录入方式。

内部分类表 Excel 只在生成 JSON 规则索引时使用，表头必须包含：

```text
一级品类、二级品类、三级品类、模块名称、子模块列表
```

当前项目不会在 Web 页面中上传内部分类表；请通过 `.env` 配置固定规则路径。

## 输出结果

审计完成后页面会出现下载链接。导出的 Excel 包含：

- `审计明细`：每条录入记录的审计结果、置信度、经营范围、错误原因、建议修正。
- `人员汇总`：按姓名统计录入数量、完整数量、正确数量、错误数量、疑似错误数量、无法判断数量、正确率。

## 企查查 API 接入说明

当前真实 API 还没申请完成，所以系统使用：

```text
app/company/mock_provider.py
```

后续拿到企查查官方 API 后，只需要补充：

```text
app/company/qichacha_provider.py
```

建议把 API Key 放到环境变量，不要写死在代码里：

```text
QICHACHA_API_KEY
QICHACHA_API_SECRET
```

## 测试

```bash
python -m pytest
```

## 目录说明

```text
app/main.py                    FastAPI 入口
app/audit/graph.py             LangGraph 审计流程
app/audit/rules.py             规则审计逻辑
app/category/rule_index.py     分类表 JSON 规则索引生成和加载
app/excel/input_reader.py      员工录入表读取
app/excel/category_reader.py   内部分类表读取
app/excel/result_writer.py     审计结果导出
app/company/mock_provider.py   mock 企业信息查询
app/company/qichacha_provider.py 企查查 API 预留实现
storage/uploads                上传文件目录
storage/outputs                输出结果目录
storage/category_rules.json    本地生成的分类规则索引，不提交 GitHub
```
