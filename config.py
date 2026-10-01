"""Конфигурация бота и безопасные настройки проекта."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

# Токен задаётся в окружении и никогда не хранится в исходном коде.
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_IDS = frozenset({5550140454, 7904866049})

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MORNING_BRIEF_HOUR = 8
MORNING_BRIEF_MINUTE = 0

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "diary.sqlite3"
VOICE_NOTES_DIR = BASE_DIR / "voice_notes"
CHARTS_DIR = BASE_DIR / "charts"
