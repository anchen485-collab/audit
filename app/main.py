import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.audit.graph import run_audit_workflow
from app.company.factory import get_company_provider
from app.core.config import ensure_storage_dirs
from app.core.logging_config import configure_logging


BASE_DIR = Path(__file__).resolve().parent
configure_logging()
logger = logging.getLogger(__name__)
app = FastAPI(title="企业录入审计 Agent", version="1.0.0")
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")


@app.get("/health")
def health():
    """健康检查接口。"""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """审计 Agent 首页，提供 Excel 上传入口。"""
    return templates.TemplateResponse(request, "index.html")


@app.post("/audit/upload", response_class=HTMLResponse)
async def upload_audit_files(
    request: Request,
    employee_file: UploadFile = File(...),
):
    """接收员工录入 Excel，使用服务端固定分类规则执行审计。"""
    _validate_xlsx(employee_file)
    job_id = f"审计结果_{uuid4().hex[:8]}"
    logger.info(
        "audit_upload_start 审计上传开始 job_id=%s employee_file=%s category_source=configured_json",
        job_id,
        employee_file.filename,
    )

    try:
        paths = ensure_storage_dirs()
        employee_path = paths["uploads"] / f"{job_id}_employee.xlsx"
        employee_path.write_bytes(await employee_file.read())
        logger.info(
            "audit_upload_saved 上传文件已保存 job_id=%s employee_path=%s",
            job_id,
            employee_path,
        )
        state = run_audit_workflow(
            employee_file=employee_path,
            output_dir=paths["outputs"],
            provider=get_company_provider(),
            job_id=job_id,
        )
    except ValueError as exc:
        logger.warning("audit_upload_validation_failed 文件格式校验失败 job_id=%s error=%s", job_id, exc)
        return _error_response(request, "文件格式不符合模板", str(exc), 400)
    except Exception as exc:
        logger.exception("audit_upload_failed 审计处理异常 job_id=%s", job_id)
        return _error_response(request, "审计处理失败", str(exc), 500)

    logger.info("audit_upload_done 审计上传处理完成 job_id=%s output_path=%s", job_id, state["output_path"])
    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "job_id": Path(state["output_path"]).stem,
            "steps": state.get("steps", []),
        },
    )


@app.get("/audit/download/{job_id}")
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
