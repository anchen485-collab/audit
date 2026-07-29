import logging
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.audit.graph import run_audit_workflow
from app.companies.providers.factory import get_company_provider
from app.core.config import ensure_storage_dirs
from app.core.models import AuditGraphState, AuditResult
from app.core.trace import elapsed_ms


BASE_DIR = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    """审计 Agent 首页，提供 Excel 上传入口。"""
    return templates.TemplateResponse(request, "index.html")


@router.post("/audit/upload", response_class=HTMLResponse)
async def upload_audit_files(
    request: Request,
    employee_file: UploadFile = File(...),
    category_file: UploadFile | None = File(None),
):
    """接收员工录入 Excel，执行审计后返回结果下载页面。"""
    upload_start = perf_counter()
    job_id = _new_job_id()
    logger.info(
        "audit_upload_start 审计上传开始 job_id=%s employee_file=%s category_file=%s",
        job_id,
        employee_file.filename,
        category_file.filename if category_file else "configured_json",
    )

    try:
        state = await _save_and_run_audit(employee_file, category_file, job_id)
    except ValueError as exc:
        logger.warning(
            "audit_upload_validation_failed 文件格式校验失败 job_id=%s error=%s duration_ms=%.2f",
            job_id,
            exc,
            elapsed_ms(upload_start),
        )
        return _error_response(request, "文件格式不符合模板", str(exc), 400)
    except HTTPException as exc:
        logger.warning(
            "audit_upload_rejected 上传参数不合法 job_id=%s error=%s duration_ms=%.2f",
            job_id,
            exc.detail,
            elapsed_ms(upload_start),
        )
        return _error_response(request, "文件格式不符合模板", str(exc.detail), exc.status_code)
    except Exception as exc:
        logger.exception("audit_upload_failed 审计处理异常 job_id=%s duration_ms=%.2f", job_id, elapsed_ms(upload_start))
        return _error_response(request, "审计处理失败", str(exc), 500)

    logger.info(
        "audit_upload_done 审计上传处理完成 job_id=%s trace_id=%s output_path=%s duration_ms=%.2f",
        job_id,
        state.get("trace_id"),
        state["output_path"],
        elapsed_ms(upload_start),
    )
    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "job_id": Path(state["output_path"]).stem,
            "steps": state.get("steps", []),
        },
    )


@router.post("/api/audit/upload")
async def upload_audit_file_api(file: UploadFile = File(...)):
    """给单页前端使用的 JSON 上传接口。"""
    upload_start = perf_counter()
    job_id = _new_job_id()
    logger.info("audit_api_upload_start 前端接口审计开始 job_id=%s employee_file=%s", job_id, file.filename)

    try:
        state = await _save_and_run_audit(file, None, job_id)
    except ValueError as exc:
        logger.warning(
            "audit_api_upload_validation_failed job_id=%s error=%s duration_ms=%.2f",
            job_id,
            exc,
            elapsed_ms(upload_start),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("audit_api_upload_failed job_id=%s duration_ms=%.2f", job_id, elapsed_ms(upload_start))
        raise HTTPException(status_code=500, detail="审计处理失败，请查看服务端控制台日志。") from exc

    logger.info(
        "audit_api_upload_done 前端接口审计完成 job_id=%s trace_id=%s duration_ms=%.2f",
        job_id,
        state.get("trace_id"),
        elapsed_ms(upload_start),
    )
    return _build_api_payload(state)


@router.get("/audit/download/{job_id}")
def download_result(job_id: str):
    """通过 job_id 下载审计结果，避免暴露服务器真实路径。"""
    if "/" in job_id or "\\" in job_id or ".." in job_id:
        logger.warning("audit_download_rejected 下载参数非法 job_id=%s", job_id)
        raise HTTPException(status_code=400, detail="非法文件名")
    paths = ensure_storage_dirs()
    result_path = paths["outputs"] / f"{job_id}.xlsx"
    if not result_path.exists():
        logger.warning("audit_download_missing 下载文件不存在 job_id=%s result_path=%s", job_id, result_path)
        raise HTTPException(status_code=404, detail="审计结果不存在")
    logger.info("audit_download_start 开始下载审计结果 job_id=%s result_path=%s", job_id, result_path)
    return FileResponse(
        path=result_path,
        filename=f"{job_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


async def _save_and_run_audit(
    employee_file: UploadFile,
    category_file: UploadFile | None,
    job_id: str,
) -> AuditGraphState:
    """保存上传文件并运行审计流程，供 HTML 和 JSON 两种入口复用。"""
    _validate_xlsx(employee_file)
    if category_file and category_file.filename:
        _validate_xlsx(category_file)

    paths = ensure_storage_dirs()
    employee_path = paths["uploads"] / f"{job_id}_employee.xlsx"
    employee_path.write_bytes(await employee_file.read())

    category_path = None
    if category_file and category_file.filename:
        category_path = paths["uploads"] / f"{job_id}_category.xlsx"
        category_path.write_bytes(await category_file.read())

    logger.info(
        "audit_upload_saved 上传文件已保存 job_id=%s employee_path=%s category_path=%s",
        job_id,
        employee_path,
        category_path or "configured_json",
    )
    return run_audit_workflow(
        employee_file=employee_path,
        category_file=category_path,
        output_dir=paths["outputs"],
        provider=get_company_provider(),
        job_id=job_id,
    )


def _build_api_payload(state: AuditGraphState) -> dict:
    """把当前项目的审计结果转换成前端工作台需要的 JSON 结构。"""
    results = state.get("results", [])
    output_stem = Path(state["output_path"]).stem
    cases = [_build_case_payload(result) for result in results]
    decisions = [_build_decision_payload(result) for result in results]
    review_tasks = [_build_review_task_payload(result) for result in results if result.needs_review]

    return {
        "batch_id": state.get("job_id", output_stem),
        "case_count": len(cases),
        "decision_count": len(decisions),
        "review_task_count": len(review_tasks),
        "metrics": _build_metrics(results),
        "cases": cases,
        "decisions": decisions,
        "review_tasks": review_tasks,
        "result_file": state["output_path"],
        "download_url": f"/audit/download/{output_stem}",
        "trace_id": state.get("trace_id", ""),
        "trace": state.get("trace", []),
    }


def _build_case_payload(result: AuditResult) -> dict:
    """生成前端表格左侧的企业录入信息。"""
    case_id = str(result.row_number)
    return {
        "case_id": case_id,
        "row_number": result.row_number,
        "employee_name": result.employee_name,
        "company_name": result.cleaned_company or result.original_company,
        "website_url": result.website_url,
        "entered_level1": result.original_category,
        "entered_level2": "",
        "entered_subcategory": result.original_subcategory,
    }


def _build_decision_payload(result: AuditResult) -> dict:
    """生成前端表格右侧的审计判断信息。"""
    return {
        "case_id": str(result.row_number),
        "action": _status_to_action(result),
        "confidence": result.confidence,
        "risk_score": _risk_score(result),
        "needs_review": result.needs_review,
        "reason": result.reason,
        "suggestion": result.suggestion,
    }


def _build_review_task_payload(result: AuditResult) -> dict:
    """把需要人工复核的审计结果转成前端任务列表。"""
    return {
        "task_id": f"review_{result.row_number}",
        "case_id": str(result.row_number),
        "priority": "high" if result.status == "疑似错误" else "normal",
        "reason": result.reason or result.error_type,
        "status": "pending",
    }


def _build_metrics(results: list[AuditResult]) -> dict:
    """计算前端指标卡片展示用的基础统计。"""
    total_count = len(results)
    review_count = sum(1 for result in results if result.needs_review)
    auto_handled_count = total_count - review_count
    return {
        "total_count": total_count,
        "auto_handled_count": auto_handled_count,
        "review_count": review_count,
        "auto_handled_rate": auto_handled_count / total_count if total_count else 0,
        "review_rate": review_count / total_count if total_count else 0,
    }


def _status_to_action(result: AuditResult) -> str:
    """把中文审计结果映射成前端筛选用的动作枚举。"""
    if result.needs_review:
        return "needs_human_review"
    if result.status == "正确":
        return "approved"
    if result.status == "错误":
        return "rejected"
    if result.status in {"无法判断", "信息缺失"}:
        return "needs_more_evidence"
    return "needs_human_review"


def _risk_score(result: AuditResult) -> int:
    """用简单规则给前端展示风险分，分数越高越需要关注。"""
    if result.status == "错误":
        return 90
    if result.status == "疑似错误":
        return 70
    if result.status in {"无法判断", "信息缺失"}:
        return 55
    return max(0, 100 - result.confidence)


def _new_job_id() -> str:
    return f"审计结果_{uuid4().hex[:8]}"


def _validate_xlsx(file: UploadFile):
    """第一版只支持 xlsx 文件。"""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail=f"{file.filename} 不是 .xlsx 文件")


def _error_response(request: Request, title: str, message: str, status_code: int) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "title": title,
            "message": message,
            "status_code": status_code,
        },
        status_code=status_code,
    )
