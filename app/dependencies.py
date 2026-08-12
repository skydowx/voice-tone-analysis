from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.repositories.batches import BatchRepository
from app.services.processor import BatchProcessor


def settings_from(request: Request) -> Settings:
    return request.app.state.settings


def repository_from(request: Request) -> BatchRepository:
    return request.app.state.repository


def processor_from(request: Request) -> BatchProcessor:
    return request.app.state.processor
