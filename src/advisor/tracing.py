"""OpenTelemetry：节点、Skill、模型调用各一个 span。

设置 OTEL_EXPORTER_OTLP_ENDPOINT（如 Langfuse/Jaeger 的 OTLP 地址）即导出；未设置时只在审计记录里留 trace_id。
Trace 只证明执行血缘，不证明结论成立。
"""
import os
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_initialized = False


def init_tracing(service: str = "stock-advisor", exporter=None) -> None:
    global _initialized
    if _initialized:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    if exporter is None and os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter()
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _initialized = True


def tracer():
    return trace.get_tracer("advisor")


@contextmanager
def span(name: str, **attrs) -> Iterator[dict]:
    """开启 span，并返回 {trace_id, span_id} 供审计记录关联。"""
    with tracer().start_as_current_span(name) as s:
        for k, v in attrs.items():
            if v is not None:
                s.set_attribute(k, str(v))
        ctx = s.get_span_context()
        ids = {"trace_id": f"{ctx.trace_id:032x}", "span_id": f"{ctx.span_id:016x}"} if ctx.is_valid else {}
        yield ids
