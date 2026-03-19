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

# One-time: purge legacy 'spotify' queue (renamed to 'metadata')
MIGRATION_MARKER="/config/.spotify_queue_purged"
if [[ ! -f "$MIGRATION_MARKER" ]]; then
    python -c "
import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
import django; django.setup()
from celery_app import app
from kombu import Queue
with app.connection_or_acquire() as conn:
    try:
        n = Queue('spotify').bind(conn.default_channel).purge()
        if n: print(f'Purged {n} messages from legacy spotify queue')
        else: print('Legacy spotify queue already clean')
    except Exception: pass
" 2>/dev/null && touch "$MIGRATION_MARKER" || true
fi

echo "🔧 Starting Celery worker..."
exec celery -A celery_app worker --loglevel=info --queues=downloads,metadata,celery --concurrency=1
