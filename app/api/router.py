from fastapi import APIRouter

from app.api.routers import auth, consumption, households, insights, inventory, products, shopping

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(households.router)
api_router.include_router(products.router)
api_router.include_router(inventory.router)
api_router.include_router(consumption.router)
api_router.include_router(insights.router)
api_router.include_router(shopping.router)
