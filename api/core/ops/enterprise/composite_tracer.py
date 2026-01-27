"""
Composite tracer that wraps multiple tracers.

When enterprise tracing is enabled, this wrapper ensures both the enterprise tracer
and any user-configured tracer are invoked. The user-configured tracer is called
in a finally block to ensure it runs even if the enterprise tracer fails.
"""

import logging

from core.ops.base_trace_instance import BaseTraceInstance
from core.ops.entities.trace_entity import BaseTraceInfo

logger = logging.getLogger(__name__)


class CompositeTracer(BaseTraceInstance):
    """
    A composite tracer that delegates to multiple tracers.

    This ensures enterprise tracing always runs while also supporting
    user-configured tracers (like Langfuse, Langsmith, etc.).
    """

    def __init__(
        self,
        enterprise_tracer: BaseTraceInstance,
        user_tracer: BaseTraceInstance | None = None,
    ):
        # Don't call super().__init__() since we don't have a config
        self.enterprise_tracer = enterprise_tracer
        self.user_tracer = user_tracer

    def trace(self, trace_info: BaseTraceInfo) -> None:
        try:
            self.enterprise_tracer.trace(trace_info)
        finally:
            if self.user_tracer:
                self.user_tracer.trace(trace_info)

    def api_check(self) -> bool:
        if self.user_tracer:
            return self.user_tracer.api_check()

    def get_project_url(self) -> str:
        if self.user_tracer:
            return self.user_tracer.get_project_url()
