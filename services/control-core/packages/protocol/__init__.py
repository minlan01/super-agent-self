"""Protocol package — execution domain v1 schemas + platform contracts.

Public API:
    from packages.protocol import SCHEMA_VERSION, v1
    from packages.protocol.schemas.v1 import Task, Run, StepRun, ...
"""
from packages.protocol.schemas.enums import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION"]
