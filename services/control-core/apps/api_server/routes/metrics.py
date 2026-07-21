"""Prometheus metrics endpoint — exposes metrics in text exposition format."""

from __future__ import annotations

from fastapi import APIRouter, Response

from packages.middleware.prometheus import Counter, Gauge, Histogram, registry

router = APIRouter()


def _format_label_pairs(labels: dict[str, str]) -> str:
    """Format a dict of labels into Prometheus label notation."""
    if not labels:
        return ""
    parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"


def _format_counter(counter: Counter) -> str:
    lines = [
        f"# HELP {counter.name} {counter.help_text}",
        f"# TYPE {counter.name} counter",
    ]
    for label_key, value in counter.all_samples():
        if counter.label_names and label_key:
            labels = dict(zip(counter.label_names, label_key))
            lines.append(f"{counter.name}{_format_label_pairs(labels)} {value}")
        else:
            lines.append(f"{counter.name} {value}")
    return "\n".join(lines)


def _format_gauge(gauge: Gauge) -> str:
    lines = [
        f"# HELP {gauge.name} {gauge.help_text}",
        f"# TYPE {gauge.name} gauge",
    ]
    for label_key, value in gauge.all_samples():
        if gauge.label_names and label_key:
            labels = dict(zip(gauge.label_names, label_key))
            lines.append(f"{gauge.name}{_format_label_pairs(labels)} {value}")
        else:
            lines.append(f"{gauge.name} {value}")
    return "\n".join(lines)


def _format_histogram_no_obs(histogram: Histogram) -> str:
    """Format histogram even when there are no observations yet."""
    lines = [
        f"# HELP {histogram.name} {histogram.help_text}",
        f"# TYPE {histogram.name} histogram",
    ]
    if not histogram.all_label_keys():
        # Emit zero-valued bucket lines for an unobserved histogram
        for bucket in histogram.buckets:
            le_val = "+Inf" if bucket == float("inf") else str(bucket)
            lines.append(f'{histogram.name}_bucket{{le="{le_val}"}} 0')
        lines.append(f"{histogram.name}_sum 0")
        lines.append(f"{histogram.name}_count 0")
    else:
        for label_key in histogram.all_label_keys():
            if histogram.label_names and label_key:
                base_labels = dict(zip(histogram.label_names, label_key))
            else:
                base_labels = {}
            samples = histogram.get_samples(base_labels)
            for metric_name, labels, value in samples:
                lines.append(f"{metric_name}{_format_label_pairs(labels)} {value}")
    return "\n".join(lines)


def generate_metrics() -> str:
    """Generate the full Prometheus text exposition format output."""
    blocks: list[str] = []

    for metric in registry.all_metrics():
        if isinstance(metric, Counter):
            blocks.append(_format_counter(metric))
        elif isinstance(metric, Gauge):
            blocks.append(_format_gauge(metric))
        elif isinstance(metric, Histogram):
            blocks.append(_format_histogram_no_obs(metric))

    return "\n\n".join(blocks) + "\n"


@router.get("/prometheus")
def prometheus_metrics() -> Response:
    """Return all collected metrics in Prometheus text exposition format."""
    return Response(
        content=generate_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
