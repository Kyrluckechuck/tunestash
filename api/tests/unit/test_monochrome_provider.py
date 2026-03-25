"""Tests for Monochrome download provider."""

import base64
import json
from unittest.mock import MagicMock, patch

from downloader.providers.monochrome import MonochromeEndpoint, MonochromeProvider


class TestMonochromeEndpointHealth:
    """Test endpoint health tracking."""

    def test_new_endpoint_is_healthy(self):
        ep = MonochromeEndpoint(url="https://api.example.com")
        assert ep.is_healthy is True

    def test_failed_endpoint_is_unhealthy(self):
        ep = MonochromeEndpoint(url="https://api.example.com")
        ep.mark_failure()
        assert ep.is_healthy is False
        assert ep.consecutive_failures == 1

    def test_success_resets_failures(self):
        ep = MonochromeEndpoint(url="https://api.example.com")
        ep.mark_failure()
        ep.mark_failure()
        ep.mark_success()
        assert ep.is_healthy is True
        assert ep.consecutive_failures == 0


class TestMonochromeSearchParsing:
    """Test search result parsing without hitting the real API."""

    def test_parse_track_result(self):
        provider = MonochromeProvider(api_urls=["https://api.example.com"])

        result = provider._parse_track_result(
            {
                "id": 12345,
                "title": "Bohemian Rhapsody",
                "artists": [{"name": "Queen"}],
                "album": {
                    "title": "A Night at the Opera",
                    "cover": "ab-cd-ef-gh",
                    "numberOfTracks": 12,
                    "releaseDate": "1975-10-31",
                },
                "duration": 354,
                "isrc": "GBUM71029604",
            },
            confidence=0.95,
        )

        assert result is not None
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"
        assert result.album == "A Night at the Opera"
        assert result.duration_ms == 354000
        assert result.isrc == "GBUM71029604"
        assert result.provider == "monochrome"

    def test_parse_track_result_missing_album(self):
        provider = MonochromeProvider(api_urls=["https://api.example.com"])

        result = provider._parse_track_result(
            {
                "id": 99999,
                "title": "Solo Track",
                "artists": [{"name": "Solo Artist"}],
                "album": {},
                "duration": 180,
            },
            confidence=0.5,
        )

        assert result is not None
        assert result.album == ""


class TestMonochromeManifestDecoding:
    """Test base64 manifest decoding for both JSON and MPD formats."""

    def test_json_manifest_with_urls(self):
        provider = MonochromeProvider(api_urls=["https://api.example.com"])

        manifest = json.dumps({"urls": ["https://cdn.tidal.com/stream.flac"]})
        manifest_b64 = base64.b64encode(manifest.encode()).decode()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "manifest": manifest_b64,
                "audioQuality": "LOSSLESS",
                "mimeType": "audio/flac",
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("downloader.providers.monochrome.requests.get") as mock_get:
            mock_get.return_value = mock_response
            ep = MonochromeEndpoint(url="https://api.example.com")
            info = provider._get_stream_info(ep, "12345", None)

        assert info is not None
        assert info["url"] == "https://cdn.tidal.com/stream.flac"
        assert info["format"] == "flac"
        assert info["bitrate_kbps"] == 1411

    def test_mpd_manifest(self):
        provider = MonochromeProvider(api_urls=["https://api.example.com"])

        mpd_xml = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period></Period></MPD>'
        manifest_b64 = base64.b64encode(mpd_xml.encode()).decode()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "manifest": manifest_b64,
                "audioQuality": "HI_RES_LOSSLESS",
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("downloader.providers.monochrome.requests.get") as mock_get:
            mock_get.return_value = mock_response
            ep = MonochromeEndpoint(url="https://api.example.com")
            info = provider._get_stream_info(ep, "12345", None)

        assert info is not None
        assert "mpd_content" in info
        assert info["mpd_content"].startswith("<MPD")
        assert info["bitrate_kbps"] == 9216

    def test_missing_manifest_returns_none(self):
        provider = MonochromeProvider(api_urls=["https://api.example.com"])

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("downloader.providers.monochrome.requests.get") as mock_get:
            mock_get.return_value = mock_response
            ep = MonochromeEndpoint(url="https://api.example.com")
            info = provider._get_stream_info(ep, "12345", None)

        assert info is None
