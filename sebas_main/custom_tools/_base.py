"""Shared plumbing for Sebas's tools."""

from __future__ import annotations

import logging
import os
from typing import Any, ClassVar

import httpx
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

USER_AGENT = "Sebas/1.0 (personal assistant)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class ToolError(Exception):
    """An expected failure, reported to the model in plain words."""


def require_env(name: str, purpose: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ToolError(f"{name} is not set in .env, so {purpose} is unavailable.")
    return value


def http_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    service: str,
) -> Any:
    """GET a JSON resource, turning HTTP failures into readable ToolErrors."""
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT, **(headers or {})},
            params=params,
            timeout=20,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach {service}: {exc}") from exc
    if response.status_code in (401, 403):
        raise ToolError(
            f"{service} rejected the credentials (HTTP {response.status_code}). "
            "The token may be expired or missing a permission."
        )
    if response.status_code >= 400:
        raise ToolError(
            f"{service} returned HTTP {response.status_code}: {response.text[:200]}"
        )
    return response.json()


class SebasTool(BaseTool):
    """A tool defined by class attributes plus a ``run`` method returning text."""

    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    timeout_seconds: ClassVar[float] = 30.0

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameter_schema(),
            category="sebas",
            timeout_seconds=self.timeout_seconds,
        )

    def parameter_schema(self) -> dict[str, Any]:
        return self.parameters

    def run(self, **params: Any) -> str:
        raise NotImplementedError

    def execute(self, **params: Any) -> ToolResult:
        try:
            return ToolResult(tool_name=self.name, content=self.run(**params))
        except ToolError as exc:
            return ToolResult(tool_name=self.name, content=str(exc), success=False)
        except Exception as exc:
            logger.exception("Tool %s failed", self.name)
            return ToolResult(
                tool_name=self.name,
                content=f"Unexpected error: {type(exc).__name__}: {exc}",
                success=False,
            )
