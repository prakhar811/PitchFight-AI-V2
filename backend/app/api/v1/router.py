"""API v1 router.

Assembles route modules. Only the health endpoint is implemented
in this scaffolding phase.
"""

from fastapi import APIRouter

from app.api.v1.routes import auth, health, pitches, scores, simulations

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(pitches.router, prefix="/pitches", tags=["pitches"])
api_router.include_router(simulations.router, prefix="/simulations", tags=["simulations"])
api_router.include_router(scores.router, prefix="/scores", tags=["scores"])
