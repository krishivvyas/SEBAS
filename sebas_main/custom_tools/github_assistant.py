"""Read-only summary of GitHub pull requests and notifications."""

from __future__ import annotations

from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError, http_get_json, require_env

_API = "https://api.github.com"


@ToolRegistry.register("github_activity")
class GitHubActivityTool(SebasTool):
    name = "github_activity"
    description = (
        "Summarise the user's GitHub activity: open pull requests they authored, "
        "pull requests awaiting their review, and unread notifications. Read-only."
    )
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum items per section (1-20, default 8).",
            }
        },
    }

    def run(self, limit: int = 8) -> str:
        token = require_env("GITHUB_PAT", "GitHub")
        limit = max(1, min(int(limit or 8), 20))
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        def get(path: str, **params):
            return http_get_json(f"{_API}{path}", headers=headers, params=params, service="GitHub")

        login = get("/user")["login"]
        sections = [f"GitHub user: {login}"]

        for title, query in (
            ("Your open pull requests", f"is:pr is:open author:{login}"),
            ("Pull requests awaiting your review", f"is:pr is:open review-requested:{login}"),
        ):
            items = get("/search/issues", q=query, sort="updated", per_page=limit)["items"]
            lines = [
                f"- {i['repository_url'].split('/repos/')[-1]}#{i['number']}: {i['title']}"
                f" (updated {i['updated_at'][:10]}, {i['comments']} comments)"
                for i in items
            ]
            sections.append(f"{title}: {len(items)}" + ("\n" + "\n".join(lines) if lines else ""))

        try:
            notes = get("/notifications", per_page=limit)
        except ToolError as exc:
            sections.append(
                f"Notifications unavailable ({exc}) Notifications need a classic "
                "token with the 'notifications' scope; fine-grained tokens cannot read them."
            )
        else:
            lines = [
                f"- {n['repository']['full_name']}: {n['subject']['title']}"
                f" ({n['subject']['type']}, {n['reason'].replace('_', ' ')})"
                for n in notes
            ]
            sections.append(
                f"Unread notifications: {len(notes)}" + ("\n" + "\n".join(lines) if lines else "")
            )
        return "\n\n".join(sections)
