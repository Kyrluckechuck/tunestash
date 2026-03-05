#!/bin/bash
set -e

echo "🚀 Starting worker service..."

# Auto-update yt-dlp on startup (YouTube frequently changes formats)
if [[ "${AUTO_UPDATE_YT_DLP:-true}" == "true" ]]; then
    echo "🔄 Checking for yt-dlp updates..."
    if python -m pip install --upgrade yt-dlp[default] --quiet 2>/dev/null; then
        echo "✅ yt-dlp updated to $(yt-dlp --version)"
    else
        echo "⚠️ Failed to update yt-dlp, continuing with existing version"
    fi
fi

echo "🔧 Starting Celery worker..."
exec celery -A celery_app worker --loglevel=info --queues=downloads,spotify,celery --concurrency=1 --max-tasks-per-child=500
