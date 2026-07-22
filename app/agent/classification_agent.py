from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from time import perf_counter
from typing import Any

import requests

from app.core.config import load_env_file
from app.core.models import CategoryRule, CompanyInfo, EmployeeRecord
from app.core.trace import elapsed_ms


logger = logging.getLogger(__name__)


@dataclass
class AgentClassificationResult:
    matched_level1: str = ""
    matched_level2: str = ""
    matched_level3: str = ""
    matched_module: str = ""
    matched_keywords: list[str] | None = None
    audit_result: str = "疑似错误"
    confidence: int = 0
    reason: str = ""
    suggestion: str = ""
    needs_review: bool = True


class OpenAICompatibleChatClient:
    """Minimal OpenAI-compatible chat completions client using requests."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)


class ClassificationAgent:
    """Use an LLM to classify cleaned website evidence against the internal category table."""

    def __init__(self, chat_client, max_category_chars: int = 70000, max_evidence_chars: int = 8000):
        self.chat_client = chat_client
        self.max_category_chars = max_category_chars
        self.max_evidence_chars = max_evidence_chars

    def classify(
        self,
        record: EmployeeRecord,
        company: CompanyInfo,
        rules: list[CategoryRule],
    ) -> AgentClassificationResult:
        classify_start = perf_counter()
        category_text = format_category_rules_for_agent(rules, self.max_category_chars)
        evidence_text = (company.business_scope or "")[: self.max_evidence_chars]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是企业分类审计 Agent。你只能根据用户提供的内部分类表和外部证据文本判断，"
                    "判断员工录入的一级分类和细分是否正确；细分可能是内部二级品类，也可能是内部三级品类。"
                    "不要把员工录入的环节作为判断正确或错误的标准。"
                    "必须从内部分类表已有一级、二级、三级类目中选择，不允许编造新分类。"
                    "如果证据不足以确定，请返回 audit_result=疑似错误 或 无法判断，并说明原因。"
                    "只输出 JSON，不要输出 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": _build_user_prompt(record, company, category_text, evidence_text),
            },
        ]
        try:
            data = self.chat_client.complete_json(messages)
            result = parse_agent_result(data)
        except Exception as exc:
            logger.info(
                "classification_agent_timing 大模型分类耗时 company=%s row=%s success=false result=异常 duration_ms=%.2f error=%s",
                record.company_name or record.company_raw,
                record.row_number,
                elapsed_ms(classify_start),
                exc.__class__.__name__,
            )
            raise
        logger.info(
            "classification_agent_timing 大模型分类耗时 company=%s row=%s success=true result=%s duration_ms=%.2f",
            record.company_name or record.company_raw,
            record.row_number,
            result.audit_result,
            elapsed_ms(classify_start),
        )
        return result


def build_classification_agent_from_env() -> ClassificationAgent | None:
    load_env_file()
    enabled = os.getenv("AUDIT_LLM_AGENT_ENABLED", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None

    api_key = os.getenv("AUDIT_LLM_API_KEY", "").strip()
    model = os.getenv("AUDIT_LLM_MODEL", "").strip()
    if not api_key or not model:
        logger.warning("classification_agent_disabled 大模型 Agent 已开启但缺少 AUDIT_LLM_API_KEY 或 AUDIT_LLM_MODEL")
        return None

    base_url = os.getenv("AUDIT_LLM_BASE_URL", "https://api.openai.com/v1").strip()
    timeout = int(os.getenv("AUDIT_LLM_TIMEOUT", "60"))
    max_category_chars = int(os.getenv("AUDIT_LLM_MAX_CATEGORY_CHARS", "70000"))
    max_evidence_chars = int(os.getenv("AUDIT_LLM_MAX_EVIDENCE_CHARS", "8000"))
    return ClassificationAgent(
        chat_client=OpenAICompatibleChatClient(api_key=api_key, model=model, base_url=base_url, timeout=timeout),
        max_category_chars=max_category_chars,
        max_evidence_chars=max_evidence_chars,
    )


def format_category_rules_for_agent(rules: list[CategoryRule], max_chars: int = 70000) -> str:
    grouped: dict[tuple[str, str, str], list[CategoryRule]] = {}
    for rule in rules:
        grouped.setdefault((rule.level1, rule.level2, rule.level3), []).append(rule)

    lines = []
    for index, ((level1, level2, level3), group) in enumerate(grouped.items(), start=1):
        modules = []
        for rule in group:
            if rule.module_name == "环节":
                continue
            keywords = "、".join(rule.keywords[:80])
            modules.append(f"{rule.module_name}: {keywords}" if keywords else rule.module_name)
        if not modules:
            continue
        line = f"{index}. 一级={level1}; 二级={level2}; 三级={level3}; 模块={' | '.join(modules)}"
        lines.append(line)

    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars] + "\n[分类表内容因长度限制被截断]"
    return text


def parse_agent_result(data: dict[str, Any]) -> AgentClassificationResult:
    keywords = data.get("matched_keywords") or []
    if isinstance(keywords, str):
        keywords = [item.strip() for item in keywords.replace("，", "、").split("、") if item.strip()]
    if not isinstance(keywords, list):
        keywords = []

    return AgentClassificationResult(
        matched_level1=str(data.get("matched_level1", "") or ""),
        matched_level2=str(data.get("matched_level2", "") or ""),
        matched_level3=str(data.get("matched_level3", "") or ""),
        matched_module=str(data.get("matched_module", "") or ""),
        matched_keywords=[str(item) for item in keywords],
        audit_result=_normalize_audit_result(str(data.get("audit_result", "") or "")),
        confidence=_clamp_confidence(data.get("confidence", 0)),
        reason=str(data.get("reason", "") or ""),
        suggestion=str(data.get("suggestion", "") or ""),
        needs_review=bool(data.get("needs_review", True)),
    )


def _build_user_prompt(record: EmployeeRecord, company: CompanyInfo, category_text: str, evidence_text: str) -> str:
    return f"""
请基于“内部分类表”和“外部证据文本”判断员工录入分类是否正确。
员工录入的细分可能是内部二级品类，也可能是内部三级品类；请结合内部分类表判断它命中哪一级。
员工录入的环节不作为判断正确或错误的标准，不要因为环节不一致判错。

员工录入：
- 企业名称：{record.company_name or record.company_raw}
- 当前一级分类：{record.category}
- 当前细分：{record.subcategory}

企查查/官网企业名称：{company.company_name}
数据来源：{company.source}

外部证据文本：
{evidence_text}

内部分类表：
{category_text}

请返回严格 JSON，字段如下：
{{
  "matched_level1": "从内部分类表选择的一级品类",
  "matched_level2": "从内部分类表选择的二级品类",
  "matched_level3": "从内部分类表选择的三级品类；如果员工细分只命中二级或无法确定则为空",
  "matched_module": "用于支持分类判断的模块名称；没有则为空",
  "matched_keywords": ["命中的内部分类表关键词"],
  "audit_result": "正确/错误/疑似错误/无法判断",
  "confidence": 0-100,
  "reason": "用外部证据解释判断依据",
  "suggestion": "如果当前一级分类或细分录入不正确，给出 一级品类 / 二级品类 或 一级品类 / 二级品类 / 三级品类；否则为空",
  "needs_review": true/false
}}
""".strip()


def _normalize_audit_result(value: str) -> str:
    if value in {"正确", "错误", "疑似错误", "无法判断"}:
        return value
    return "疑似错误"


def _clamp_confidence(value) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(number, 100))
