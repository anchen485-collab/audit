from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes.audit import router as audit_router
from app.api.routes.health import router as health_router
from app.core.logging_config import configure_logging


BASE_DIR = Path(__file__).resolve().parent
configure_logging()

app = FastAPI(title="企业录入审计 Agent", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")
app.include_router(health_router)
app.include_router(audit_router)
