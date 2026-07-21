from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.audit.graph import run_audit_workflow
from app.company.factory import get_company_provider
from app.core.config import ensure_storage_dirs


BASE_DIR = Path(__file__).resolve().parent
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
    category_file: UploadFile = File(...),
):
    """接收两份 Excel，执行审计并返回下载链接。"""
    _validate_xlsx(employee_file)
    _validate_xlsx(category_file)
    paths = ensure_storage_dirs()
    job_id = f"审计结果_{uuid4().hex[:8]}"
    employee_path = paths["uploads"] / f"{job_id}_employee.xlsx"
    category_path = paths["uploads"] / f"{job_id}_category.xlsx"
    employee_path.write_bytes(await employee_file.read())
    category_path.write_bytes(await category_file.read())

    state = run_audit_workflow(
        employee_file=employee_path,
        category_file=category_path,
        output_dir=paths["outputs"],
        provider=get_company_provider(),
        job_id=job_id,
    )
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
        raise HTTPException(status_code=400, detail="非法文件名")
    paths = ensure_storage_dirs()
    result_path = paths["outputs"] / f"{job_id}.xlsx"
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="审计结果不存在")
    return FileResponse(
        path=result_path,
        filename=f"{job_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _validate_xlsx(file: UploadFile):
    """第一版只支持 xlsx 文件。"""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail=f"{file.filename} 不是 .xlsx 文件")
