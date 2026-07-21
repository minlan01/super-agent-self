"""Auto-import all tool modules to trigger @tool_registry.register() decorators.

Adding a new tool = create the tool file + add one import line here.
"""

from packages.agent_core import sub_agent  # noqa: F401  (DelegateTask)
from packages.executor.tools import (
    bash_tool,  # noqa: F401
    browser_enhanced,  # noqa: F401
    browser_tools,  # noqa: F401
    desktop_tools,  # noqa: F401
    file_tools,  # noqa: F401
    messaging_tool,  # noqa: F401
    personal_tools,  # noqa: F401
    web_search_tool,  # noqa: F401
)
