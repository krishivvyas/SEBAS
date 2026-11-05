"""Sebas's custom tools. Importing this package registers them with OpenJarvis.

The names Sebas actually receives are listed under [agent] tools in
configs/sebas/config.toml.
"""

from custom_tools import (  # noqa: F401
    devops_manager,
    github_assistant,
    laptop,
    leisure_tracker,
    memory,
    morning_briefing,
)
