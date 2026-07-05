import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from .config import get_settings
from .api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"ZeroHour starting — mode: {settings.trading_mode}")
    try:
        from .database import init_db
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"DB init skipped: {e}")
    yield
    logger.info("ZeroHour shutting down")


app = FastAPI(
    title="ZeroHour Trading API",
    version="0.1.0",
    description="台美時間差量化交易系統",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# API Key 驗證（老闆 2026-07-06 核准）。settings.api_key 為空 = 停用（本地開發）。
# 生產金鑰由老闆執行 fly secrets set API_KEY=...（紅線：模型不得動 secrets）。
# 豁免：/api/v1/health（Fly 健康檢查與前端 mode 徽章）、OPTIONS（CORS preflight）、
# 非 /api/v1 路徑（dashboard 首頁本身不需 key，資料載入才需要）。
AUTH_EXEMPT_PATHS = {"/api/v1/health"}


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    if (
        settings.api_key
        and request.method != "OPTIONS"
        and request.url.path.startswith("/api/v1")
        and request.url.path not in AUTH_EXEMPT_PATHS
    ):
        if request.headers.get("X-API-Key") != settings.api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid or missing API key"},
            )
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)
