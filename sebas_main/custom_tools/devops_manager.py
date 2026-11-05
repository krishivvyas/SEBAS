"""Read-only views of Vercel deployments and AWS EC2 instance health."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError, http_get_json, require_env


def _age(epoch_ms: int | float | None) -> str:
    if not epoch_ms:
        return "unknown time"
    minutes = int((datetime.now(timezone.utc).timestamp() * 1000 - epoch_ms) / 60000)
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} h ago"
    return f"{minutes // 1440} days ago"


@ToolRegistry.register("vercel_deployments")
class VercelDeploymentsTool(SebasTool):
    name = "vercel_deployments"
    description = (
        "List the most recent Vercel deployments with their state (READY, "
        "BUILDING, ERROR, CANCELED), target environment, age, URL and commit "
        "message. Read-only."
    )
    parameters = {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Vercel project name or ID. Omit for all projects.",
            },
            "limit": {
                "type": "integer",
                "description": "How many deployments to list (1-20, default 5).",
            },
        },
    }

    def run(self, project: str = "", limit: int = 5) -> str:
        token = require_env("VERCEL_TOKEN", "Vercel deployment status")
        params: dict = {"limit": max(1, min(int(limit or 5), 20))}
        if project:
            params["projectId"] = project
        if team := os.environ.get("VERCEL_TEAM_ID", "").strip():
            params["teamId"] = team
        data = http_get_json(
            "https://api.vercel.com/v6/deployments",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            service="Vercel",
        )
        deployments = data.get("deployments", [])
        if not deployments:
            return "No deployments found" + (f" for project {project}." if project else ".")
        lines = []
        for d in deployments:
            state = d.get("readyState") or d.get("state") or "UNKNOWN"
            commit = (d.get("meta") or {}).get("githubCommitMessage", "")
            commit = commit.splitlines()[0][:80] if commit else ""
            lines.append(
                f"- {d.get('name', '?')}: {state}, {d.get('target') or 'preview'}, "
                f"{_age(d.get('created'))}, https://{d.get('url', '')}"
                + (f', commit "{commit}"' if commit else "")
            )
        return "\n".join(lines)


@ToolRegistry.register("aws_instance_health")
class AwsInstanceHealthTool(SebasTool):
    name = "aws_instance_health"
    description = (
        "Report every EC2 instance in a region: name, ID, type, state, and the "
        "system and instance status checks. Read-only."
    )
    parameters = {
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "description": "AWS region such as us-east-1. Defaults to AWS_DEFAULT_REGION.",
            }
        },
    }
    timeout_seconds = 45.0

    def run(self, region: str = "") -> str:
        require_env("AWS_ACCESS_KEY_ID", "AWS instance health")
        require_env("AWS_SECRET_ACCESS_KEY", "AWS instance health")
        region = region or require_env("AWS_DEFAULT_REGION", "AWS instance health")
        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError as exc:
            raise ToolError("boto3 is not installed (requirements_tools.txt).") from exc

        ec2 = boto3.client("ec2", region_name=region)
        try:
            reservations = ec2.describe_instances()["Reservations"]
            statuses = ec2.describe_instance_status(IncludeAllInstances=True)[
                "InstanceStatuses"
            ]
        except ClientError as exc:
            raise ToolError(f"AWS refused the request: {exc}") from exc
        except BotoCoreError as exc:
            raise ToolError(f"Could not reach AWS: {exc}") from exc

        checks = {
            s["InstanceId"]: (
                s.get("SystemStatus", {}).get("Status", "n/a"),
                s.get("InstanceStatus", {}).get("Status", "n/a"),
            )
            for s in statuses
        }
        lines = []
        for reservation in reservations:
            for inst in reservation["Instances"]:
                iid = inst["InstanceId"]
                name = next(
                    (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                    "(unnamed)",
                )
                system, instance = checks.get(iid, ("n/a", "n/a"))
                lines.append(
                    f"- {name} ({iid}, {inst.get('InstanceType')}): "
                    f"{inst['State']['Name']}, system check {system}, "
                    f"instance check {instance}"
                )
        return "\n".join(lines) if lines else f"No EC2 instances in {region}."
