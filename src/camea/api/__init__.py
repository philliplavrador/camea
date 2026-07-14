"""The HTTP layer.

`schemas.py` is THE CONTRACT: every request and response body is a pydantic model there,
and the TypeScript client is generated from the OpenAPI schema those models produce.

Dependency arrow (one-way, never violated):  api -> features -> core -> engine
"""
