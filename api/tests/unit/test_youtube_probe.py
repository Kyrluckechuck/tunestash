"""Tests for YouTubeMusicProvider.probe_auth against the probe child's result shape."""

from unittest.mock import PropertyMock, patch

from downloader.providers import youtube
from downloader.providers.youtube import YouTubeMusicProvider


def _probe(child_result):
    provider = YouTubeMusicProvider()
    with (
        patch.object(
            YouTubeMusicProvider,
            "_po_token",
            new_callable=PropertyMock,
            return_value="test-po-token",
        ),
        patch.object(youtube, "_run_yt_dlp_child", return_value=child_result),
    ):
        return provider.probe_auth()


def test_probe_reports_success_from_format_count():
    # The probe child returns {"formats": <count>} rather than the format list.
    assert _probe({"formats": 33}) == (True, "Resolved 33 formats for probe video")


def test_probe_reports_failure_when_no_formats():
    assert _probe({"formats": 0}) == (False, "Probe returned no playable formats")


def test_probe_reports_failure_when_child_returns_nothing():
    assert _probe(None) == (False, "Probe returned no playable formats")
