"""Работа с локальной базой SQLite дневника."""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from config import DATABASE_PATH, MOSCOW_TZ


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Открывает соединение с настройками для надёжной работы SQLite."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def today_moscow() -> date:
    """Возвращает текущую календарную дату в часовом поясе Москвы."""
    return datetime.now(MOSCOW_TZ).date()


def init_db() -> None:
    """Создаёт таблицы дневника, если база запускается впервые."""
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('Рабочие', 'Личные')),
                due_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_user_date
                ON tasks(user_id, due_date);
            CREATE TABLE IF NOT EXISTS calories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                amount INTEGER NOT NULL CHECK (amount > 0),
                eaten_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_calories_user_time
                ON calories(user_id, eaten_at);
            CREATE TABLE IF NOT EXISTS voice_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                note_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_voice_user_date
                ON voice_notes(user_id, note_date);
            """
        )


def register_user(user_id: int, username: str | None) -> None:
    """Добавляет разрешённого пользователя или обновляет его имя."""
    now = datetime.now(MOSCOW_TZ).isoformat(timespec="seconds")
    with _connect() as connection:
        connection.execute(
            """INSERT INTO users (user_id, username, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username = excluded.username""",
            (user_id, username, now),
        )


def add_task(user_id: int, title: str, category: str) -> int:
    """Сохраняет задачу на сегодня и возвращает её идентификатор."""
    now = datetime.now(MOSCOW_TZ)
    with _connect() as connection:
        cursor = connection.execute(
            """INSERT INTO tasks (user_id, title, category, due_date, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, title, category, now.date().isoformat(), now.isoformat(timespec="seconds")),
        )
        return int(cursor.lastrowid)


def get_tasks(user_id: int, task_date: date | None = None) -> list[dict[str, Any]]:
    """Возвращает задачи пользователя за выбранный день."""
    selected_date = (task_date or today_moscow()).isoformat()
    with _connect() as connection:
        rows = connection.execute(
            """SELECT id, title, category, due_date, completed_at
               FROM tasks WHERE user_id = ? AND due_date = ?
               ORDER BY completed_at IS NOT NULL, id""",
            (user_id, selected_date),
        ).fetchall()
    return [dict(row) for row in rows]


def complete_task(user_id: int, task_id: int) -> bool:
    """Отмечает задачу завершённой, не затрагивая задачи других пользователей."""
    completed_at = datetime.now(MOSCOW_TZ).isoformat(timespec="seconds")
    with _connect() as connection:
        cursor = connection.execute(
            """UPDATE tasks SET completed_at = ?
               WHERE id = ? AND user_id = ? AND completed_at IS NULL""",
            (completed_at, task_id, user_id),
        )
        return cursor.rowcount == 1


def add_calories(user_id: int, amount: int) -> int:
    """Сохраняет запись о калориях и возвращает её идентификатор."""
    eaten_at = datetime.now(MOSCOW_TZ).isoformat(timespec="seconds")
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO calories (user_id, amount, eaten_at) VALUES (?, ?, ?)",
            (user_id, amount, eaten_at),
        )
        return int(cursor.lastrowid)


def get_daily_calories(user_id: int, day: date | None = None) -> int:
    """Суммирует калории за указанный день по московскому времени."""
    selected_date = (day or today_moscow()).isoformat()
    with _connect() as connection:
        row = connection.execute(
            """SELECT COALESCE(SUM(amount), 0) AS total
               FROM calories WHERE user_id = ? AND substr(eaten_at, 1, 10) = ?""",
            (user_id, selected_date),
        ).fetchone()
    return int(row["total"])


def add_voice_note(user_id: int, file_path: str, note_date: date | None = None) -> int:
    """Сохраняет путь к голосовой заметке и её дату в дневнике."""
    now = datetime.now(MOSCOW_TZ)
    selected_date = note_date or now.date()
    with _connect() as connection:
        cursor = connection.execute(
            """INSERT INTO voice_notes (user_id, file_path, note_date, created_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, file_path, selected_date.isoformat(), now.isoformat(timespec="seconds")),
        )
        return int(cursor.lastrowid)


def get_weekly_stats(user_id: int, end_date: date | None = None) -> list[dict[str, int | str]]:
    """Возвращает количество выполненных задач и калорий за последние семь дней."""
    last_day = end_date or today_moscow()
    first_day = last_day - timedelta(days=6)
    with _connect() as connection:
        rows = connection.execute(
            """WITH RECURSIVE days(day) AS (
                   SELECT date(?)
                   UNION ALL
                   SELECT date(day, '+1 day') FROM days WHERE day < date(?)
               )
               SELECT days.day,
                      (SELECT COUNT(*) FROM tasks
                       WHERE tasks.user_id = ? AND tasks.due_date = days.day
                         AND tasks.completed_at IS NOT NULL) AS completed_tasks,
                      (SELECT COALESCE(SUM(calories.amount), 0) FROM calories
                       WHERE calories.user_id = ?
                         AND substr(calories.eaten_at, 1, 10) = days.day) AS calories
               FROM days ORDER BY days.day""",
            (first_day.isoformat(), last_day.isoformat(), user_id, user_id),
        ).fetchall()
    return [dict(row) for row in rows]
