# 企业录入审计 Agent — 项目总结

## 项目概述

**企业录入审计 Agent** 是一个基于 FastAPI 的 Web 应用，用于审计员工在 Excel 中录入的企业分类是否与内部品类分类表一致。系统通过关键词匹配和评分机制，自动判定每条录入记录的归类是否正确。

- **当前版本**: v1.0
- **技术栈**: Python 3.x + FastAPI + LangGraph + openpyxl
- **运行方式**: `uvicorn app.main:app`
- **审计方式**: 纯规则引擎（无 LLM，无 AI）

---

## 核心功能

1. **双文件上传**: 用户通过 Web 页面上传员工录入表 + 内部品类分类表（均为 `.xlsx`）
2. **企业信息查询**: 根据录入的企业名称，查询企业的经营范围（支持 Mock 数据和企查查 API）
3. **规则匹配审计**: 基于关键词命中打分，自动判定每条记录为"正确/错误/疑似错误/无法判断/信息缺失"
4. **结果导出**: 生成带颜色标记的审计明细表 + 按人员汇总的统计表
5. **人员绩效统计**: 按姓名汇总每个人的正确率、错误数、疑似错误数

---

## 项目结构

```
audit/
├── app/
│   ├── main.py                      # FastAPI 入口，路由定义
│   ├── core/
│   │   ├── config.py                # 环境变量加载、存储目录管理
│   │   └── models.py                # 数据模型（dataclass / TypedDict）
│   ├── audit/
│   │   ├── graph.py                 # LangGraph 工作流编排（6节点流水线）
│   │   ├── nodes.py                 # 6个图节点函数实现
│   │   ├── rules.py                 # 核心审计判定规则
│   │   ├── scoring.py               # 关键词评分引擎
│   │   └── summary.py               # 人员汇总统计
│   ├── company/
│   │   ├── provider.py              # 企业信息查询抽象基类
│   │   ├── factory.py               # Provider 工厂函数
│   │   ├── mock_provider.py         # Mock 数据实现
│   │   ├── qichacha_provider.py     # 企查查 API 实现
│   │   └── cache.py                 # JSON 文件缓存
│   ├── excel/
│   │   ├── input_reader.py          # 员工录入表读取
│   │   ├── category_reader.py       # 品类分类表读取（含合并单元格处理）
│   │   └── result_writer.py         # 审计结果 Excel 导出
│   └── web/
│       ├── templates/index.html     # 上传页面
│       ├── templates/result.html    # 结果页面
│       └── static/styles.css        # 样式
├── tests/                           # 8个测试文件，覆盖核心模块
├── docs/
│   └── website-crawl-audit-plan.md  # 网站爬取审计扩展计划
├── requirements.txt
└── README.md
```

---

## 架构设计

### 数据流

```
用户浏览器 ──(上传Excel)──> FastAPI ──> LangGraph 工作流 ──> 输出 Excel
                                  │
                                  ├── 1. read_employee     读取员工录入表
                                  ├── 2. read_category     读取品类分类规则
                                  ├── 3. query_company     查询企业经营范围
                                  ├── 4. match_rules       关键词匹配 + 评分
                                  ├── 5. build_summary     按人员汇总
                                  └── 6. export_result     写出审计结果 Excel
```

### 设计模式

| 模式 | 应用位置 | 说明 |
|------|----------|------|
| **Provider 模式** | `company/provider.py` | 抽象企业信息查询接口，可切换 Mock / 企查查 / 爬虫 |
| **工厂模式** | `company/factory.py` | 根据环境变量 `COMPANY_PROVIDER` 创建对应实例 |
| **状态图流水线** | `audit/graph.py` | LangGraph `StateGraph`，6 节点链式执行 |
| **无状态服务** | 整体 | 无数据库，状态仅存在于单次请求的 `AuditGraphState` 中 |

---

## 核心审计逻辑

### 评分规则 (`app/audit/scoring.py`)

对于每条员工录入记录，系统将该记录填写的"一级分类 + 二级分类 + 细分"与品类规则表中的每一组 `(一级品类, 二级品类, 三级品类)` 进行匹配打分：

| 匹配项 | 分值 | 上限 |
|--------|------|------|
| 一级分类命中品类名称关键词 | +20/个 | — |
| 细分命中子模块关键词 | +20/个 | — |
| 环节命中模块名称 | +5/次 | — |
| 企业经营范围命中子模块关键词 | +12/个 | 45 |
| 环节命中子模块关键词 | +6/个 | 20 |

### 判定规则 (`app/audit/rules.py`)

按优先级依次判断：

1. **必填字段为空** → `信息缺失`
2. **企业查询无结果** → `无法判断`
3. **当前分类得分 ≥ 80** → `正确`
4. **存在更优分类（得分 ≥ 35）且当前得分 < 60** → `错误`（附带正确分类建议）
5. **其他情况** → `疑似错误`（需人工复核）

---

## 关键技术细节

- **合并单元格处理** (`category_reader.py`): 读取品类表时自动继承上方非空值，正确处理 Excel 合并单元格
- **企业名称清洗** (`rules.py`): 自动剥离员工在名称栏附加的 URL
- **企查查 API 认证** (`qichacha_provider.py`): MD5(token = api_key + timespan + api_secret)
- **结果着色** (`result_writer.py`): 正确=绿色，错误=红色，疑似错误=橙色，无法判断=灰色，信息缺失=蓝色
- **路径遍历防护** (`main.py`): 下载接口校验文件名不含 `..` 和 `/`
- **JSON 缓存** (`cache.py`): 同一批次中相同企业只查询一次

---

## 依赖项

```
fastapi, uvicorn, langgraph, openpyxl, pydantic,
python-multipart, requests, jinja2, pytest, httpx
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `COMPANY_PROVIDER` | 企业信息提供方 | `mock` |
| `QICHACHA_API_KEY` | 企查查 API Key | — |
| `QICHACHA_API_SECRET` | 企查查 API Secret | — |
| `QICHACHA_ENDPOINT` | 企查查接口地址 | — |
| `AUDIT_STORAGE_DIR` | 存储根目录 | `storage/` |

---

## 已知边界

- **无 LLM 参与**: 当前版本不使用任何 AI 模型，纯关键词规则引擎
- **无用户认证**: 无需登录，任何人可访问上传页面
- **无人工复核界面**: 审计结果仅以 Excel 形式导出，无在线审阅功能
- **企查查 API 未正式接入**: 代码已完整实现但默认使用 Mock 数据

---

## 测试覆盖

8 个测试文件覆盖了上传 API、品类读取、Excel 读取、公司 Provider 工厂、配置加载、企查查 Provider、规则引擎、以及端到端工作流。

---

## 未来扩展方向

`docs/website-crawl-audit-plan.md` 中规划了使用网站爬取替代企查查 API 的方案，分为 5 个 Sprint，通过爬取企业官网的"关于我们"、"案例展示"等页面获取经营范围的文本证据。
