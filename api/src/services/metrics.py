"""
Metrics service for recording and querying operational metrics.

This provides a simple interface for tracking things like fallback download
success rates, endpoint reliability, and other operational insights.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Union

from django.db.models import Count, Sum
from django.db.models.functions import TruncDay, TruncHour
from django.utils import timezone

from library_manager.models import AppMetric, MetricType


@dataclass
class MetricSummary:
    """Summary of a metric over a time period."""

    name: str
    total: Decimal
    count: int
    first_recorded: Optional[datetime]
    last_recorded: Optional[datetime]


@dataclass
class MetricTimeSeries:
    """Time series data for a metric."""

    name: str
    period: str  # "hour" or "day"
    data: list[dict]  # [{"timestamp": datetime, "value": Decimal, "count": int}, ...]


class MetricsService:
    """
    Service for recording and querying application metrics.

    Usage:
        # Record a counter increment
        MetricsService.increment("fallback.tidal.success")

        # Record with labels for filtering
        MetricsService.increment(
            "fallback.attempt",
            labels={"provider": "tidal", "reason": "spotdl_failed"}
        )

        # Record a gauge value
        MetricsService.record("queue.depth", 42)

        # Get summary for last 24 hours
        summary = MetricsService.get_summary("fallback.tidal.success", hours=24)

        # Get time series for dashboard
        series = MetricsService.get_time_series("fallback.tidal.success", days=7)
    """

    @staticmethod
    def increment(
        name: str,
        value: float = 1,
        labels: Optional[dict] = None,
    ) -> AppMetric:
        """
        Increment a counter metric.

        Args:
            name: Metric name (e.g., "fallback.tidal.success")
            value: Amount to increment by (default 1)
            labels: Optional labels for filtering

        Returns:
            The created AppMetric record
        """
        return AppMetric.objects.create(
            name=name,
            metric_type=MetricType.COUNTER,
            value=Decimal(str(value)),
            labels=labels or {},
        )

    @staticmethod
    def record(
        name: str,
        value: float,
        labels: Optional[dict] = None,
    ) -> AppMetric:
        """
        Record a gauge metric (point-in-time value).

        Args:
            name: Metric name (e.g., "queue.depth")
            value: The current value
            labels: Optional labels for filtering

        Returns:
            The created AppMetric record
        """
        return AppMetric.objects.create(
            name=name,
            metric_type=MetricType.GAUGE,
            value=Decimal(str(value)),
            labels=labels or {},
        )

    @staticmethod
    def get_summary(
        name: str,
        hours: Optional[int] = None,
        days: Optional[int] = None,
        labels: Optional[dict] = None,
    ) -> MetricSummary:
        """
        Get summary statistics for a metric.

        Args:
            name: Metric name to query
            hours: Look back this many hours (mutually exclusive with days)
            days: Look back this many days (mutually exclusive with hours)
            labels: Filter by labels (partial match)

        Returns:
            MetricSummary with total, count, and time range
        """
        queryset = AppMetric.objects.filter(name=name)

        if hours:
            since = timezone.now() - timedelta(hours=hours)
            queryset = queryset.filter(recorded_at__gte=since)
        elif days:
            since = timezone.now() - timedelta(days=days)
            queryset = queryset.filter(recorded_at__gte=since)

        if labels:
            for key, value in labels.items():
                queryset = queryset.filter(labels__contains={key: value})

        aggregates = queryset.aggregate(
            total=Sum("value"),
            count=Count("id"),
        )

        # Get time range
        first = queryset.order_by("recorded_at").first()
        last = queryset.order_by("-recorded_at").first()

        return MetricSummary(
            name=name,
            total=aggregates["total"] or Decimal("0"),
            count=aggregates["count"] or 0,
            first_recorded=first.recorded_at if first else None,
            last_recorded=last.recorded_at if last else None,
        )

    @staticmethod
    def get_time_series(
        name: str,
        days: int = 7,
        granularity: str = "hour",
        labels: Optional[dict] = None,
    ) -> MetricTimeSeries:
        """
        Get time series data for a metric (for charts).

        Args:
            name: Metric name to query
            days: Look back this many days
            granularity: "hour" or "day"
            labels: Filter by labels (partial match)

        Returns:
            MetricTimeSeries with bucketed data
        """
        since = timezone.now() - timedelta(days=days)
        queryset = AppMetric.objects.filter(
            name=name,
            recorded_at__gte=since,
        )

        if labels:
            for key, value in labels.items():
                queryset = queryset.filter(labels__contains={key: value})

        # Group by time bucket
        trunc_func: Union[TruncDay, TruncHour]
        if granularity == "day":
            trunc_func = TruncDay("recorded_at")
        else:
            trunc_func = TruncHour("recorded_at")

        data = list(
            queryset.annotate(bucket=trunc_func)
            .values("bucket")
            .annotate(
                value=Sum("value"),
                count=Count("id"),
            )
            .order_by("bucket")
        )

        # Convert to cleaner format
        formatted_data = [
            {
                "timestamp": item["bucket"],
                "value": item["value"],
                "count": item["count"],
            }
            for item in data
        ]

        return MetricTimeSeries(
            name=name,
            period=granularity,
            data=formatted_data,
        )

    @staticmethod
    def get_all_metric_names(days: int = 7) -> list[str]:
        """
        Get all unique metric names recorded in the time period.

        Args:
            days: Look back this many days

        Returns:
            List of unique metric names
        """
        since = timezone.now() - timedelta(days=days)
        return list(
            AppMetric.objects.filter(recorded_at__gte=since)
            .values_list("name", flat=True)
            .distinct()
            .order_by("name")
        )

    @staticmethod
    def cleanup_old_metrics(days: int = 30) -> int:
        """
        Delete metrics older than the specified number of days.

        Args:
            days: Delete metrics older than this

        Returns:
            Number of records deleted
        """
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = AppMetric.objects.filter(recorded_at__lt=cutoff).delete()
        return deleted

    @staticmethod
    def get_fallback_metrics(days: int = 7) -> dict:
        """
        Get aggregated metrics for the fallback download provider.

        Args:
            days: Look back this many days

        Returns:
            Dictionary with total_attempts, total_successes, total_failures,
            success_rate, time_series, and failure_reasons
        """
        since = timezone.now() - timedelta(days=days)

        # Get totals for each metric type
        attempts = AppMetric.objects.filter(
            name="fallback.attempt", recorded_at__gte=since
        ).aggregate(total=Sum("value"), count=Count("id"))

        successes = AppMetric.objects.filter(
            name="fallback.success", recorded_at__gte=since
        ).aggregate(total=Sum("value"), count=Count("id"))

        failures = AppMetric.objects.filter(
            name="fallback.failure", recorded_at__gte=since
        ).aggregate(total=Sum("value"), count=Count("id"))

        total_attempts = int(attempts["total"] or 0)
        total_successes = int(successes["total"] or 0)
        total_failures = int(failures["total"] or 0)

        # Calculate success rate (avoid division by zero)
        success_rate = 0.0
        if total_attempts > 0:
            success_rate = round((total_successes / total_attempts) * 100, 1)

        # Get time series for attempts (hourly)
        time_series_data = list(
            AppMetric.objects.filter(name="fallback.attempt", recorded_at__gte=since)
            .annotate(bucket=TruncHour("recorded_at"))
            .values("bucket")
            .annotate(value=Sum("value"), count=Count("id"))
            .order_by("bucket")
        )

        time_series = [
            {
                "timestamp": item["bucket"],
                "value": float(item["value"]),
                "count": item["count"],
            }
            for item in time_series_data
        ]

        # Get failure reasons breakdown
        failure_reasons_data = (
            AppMetric.objects.filter(name="fallback.failure", recorded_at__gte=since)
            .values("labels__reason")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        failure_reasons = [
            {"reason": item["labels__reason"] or "unknown", "count": item["count"]}
            for item in failure_reasons_data
        ]

        return {
            "total_attempts": total_attempts,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "success_rate": success_rate,
            "time_series": time_series,
            "failure_reasons": failure_reasons,
        }
