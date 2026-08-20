"""Vercel serverless entrypoint for the resilient FastAPI web app."""

from webhook_server import app

__all__ = ["app"]
