# 企业录入审计 Agent Version 1.0

这是第一版审计 Agent，用于审计员工录入 Excel 中的企业分类是否合理。

## 当前能力

- 提供简单 Web 页面上传 Excel。
- 支持上传员工录入表和内部分类表。
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

如果暂停企查查 API，改用官网爬取模式：

```text
COMPANY_PROVIDER=website
WEBSITE_CRAWL_MAX_PAGES=4
WEBSITE_CRAWL_TIMEOUT=8
WEBSITE_CRAWL_TARGET_MODULES=公司简介,经典案例,业务领域
WEBSITE_CRAWL_CONCURRENCY=5
```

官网模式要求员工录入 Excel 的“企业名称&官网”单元格里存在真实超链接。系统只会读取公开官网页面，并优先抓取：

```text
公司简介
经典案例
业务领域
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
日期、姓名、一级分类、细分、企业名称&官网、环节
```

内部分类表 Excel 表头必须包含：

```text
一级品类、二级品类、三级品类、模块名称、子模块列表
```

当前项目中的 `最终分类表.xlsx` 可以作为内部分类表上传。

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
app/excel/input_reader.py      员工录入表读取
app/excel/category_reader.py   内部分类表读取
app/excel/result_writer.py     审计结果导出
app/company/mock_provider.py   mock 企业信息查询
app/company/qichacha_provider.py 企查查 API 预留实现
storage/uploads                上传文件目录
storage/outputs                输出结果目录
```
