from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from app.api.v1.routes_health import router as health_router
from app.api.v1.routes_kyc_session import router as kyc_session_router
from app.api.v1.admin_kyc import router as admin_kyc_router


# Create FastAPI app 
app = FastAPI(
    title="SwiftKyc Backend",
    version="1.0.0",
    description="Digital KYC backend for SwiftKyc",
)

# Serve static files (JS, CSS, images)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

API_PREFIX = "/api/v1"

# Include backend routes
app.include_router(health_router, prefix=API_PREFIX)
app.include_router(kyc_session_router, prefix=API_PREFIX)
app.include_router(admin_kyc_router, prefix=API_PREFIX)


# Serve homepage (index.html) at root
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("app/static/index.html", encoding="utf-8") as f:
        return f.read()

