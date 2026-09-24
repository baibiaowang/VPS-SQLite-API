from fastapi import FastAPI
from .api import app as api_app
from .admin import router as admin_router

app = api_app
app.include_router(admin_router)
