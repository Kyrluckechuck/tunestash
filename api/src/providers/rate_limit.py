"""Shared API rate-limiting using the database-backed APIRateLimitState model."""

import time


def check_api_rate_limit(api_name: str, default_rate: float = 1.0) -> None:
    """Check and respect API rate limit for the named API.

    Uses the APIRateLimitState model to track request counts per second window.
    Sleeps if the rate limit has been reached. Silently ignores errors to avoid
    blocking callers if the rate-limit state table is unavailable.
    """
    from django.utils import timezone

    from library_manager.models import APIRateLimitState

    try:
        state, _ = APIRateLimitState.objects.get_or_create(
            api_name=api_name,
            defaults={"max_requests_per_second": default_rate},
        )
        now_ts = time.time()
        window_start_ts = state.window_start.timestamp() if state.window_start else 0

        if now_ts - window_start_ts >= 1.0:
            state.request_count = 1
            state.window_start = timezone.now()
            state.save(update_fields=["request_count", "window_start"])
        elif state.request_count >= state.max_requests_per_second:
            sleep_time = 1.0 - (now_ts - window_start_ts)
            if sleep_time > 0:
                time.sleep(sleep_time)
            state.request_count = 1
            state.window_start = timezone.now()
            state.save(update_fields=["request_count", "window_start"])
        else:
            state.request_count += 1
            state.save(update_fields=["request_count"])
    except Exception:
        pass
