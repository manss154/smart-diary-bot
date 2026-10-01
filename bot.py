"""Точка входа Telegram-бота и настройка ежедневного расписания."""

import asyncio
import logging
import random
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    ALLOWED_USER_IDS,
    BOT_TOKEN,
    MORNING_BRIEF_HOUR,
    MORNING_BRIEF_MINUTE,
    MOSCOW_TZ,
)
from database import init_db
from handlers import main_menu, router, send_morning_brief
from smiles_and_quotes import random_reminder

logger = logging.getLogger(__name__)


async def send_morning_briefs(bot: Bot) -> None:
    """Рассылает утреннюю сводку всем пользователям из белого списка."""
    for user_id in ALLOWED_USER_IDS:
        try:
            await send_morning_brief(bot, user_id)
        except TelegramAPIError:
            logger.exception("Не удалось отправить утреннюю сводку пользователю %s", user_id)


async def send_day_reminder(bot: Bot, user_id: int) -> None:
    """Отправляет одно случайное напоминание из дневной подборки."""
    try:
        await bot.send_message(user_id, random_reminder(), reply_markup=main_menu())
    except TelegramAPIError:
        logger.exception("Не удалось отправить напоминание пользователю %s", user_id)


def schedule_daily_reminders(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    """Ставит четыре случайных напоминания на оставшуюся часть дня по Москве."""
    now = datetime.now(MOSCOW_TZ)
    start_minute = 9 * 60
    end_minute = 21 * 60
    selected_minutes = sorted(random.sample(range(start_minute, end_minute), k=4))

    for user_id in ALLOWED_USER_IDS:
        for minute_of_day in selected_minutes:
            hour, minute = divmod(minute_of_day, 60)
            run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if run_at <= now:
                continue
            job_id = f"reminder_{user_id}_{now.date().isoformat()}_{hour:02d}{minute:02d}"
            scheduler.add_job(
                send_day_reminder,
                trigger="date",
                run_date=run_at,
                args=(bot, user_id),
                id=job_id,
                replace_existing=True,
                misfire_grace_time=300,
            )


async def main() -> None:
    """Инициализирует хранилище, планировщик и начинает получать обновления."""
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не задан TELEGRAM_BOT_TOKEN. Отзови опубликованный токен в BotFather "
            "и задай новый токен в переменной окружения."
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    scheduler = AsyncIOScheduler(
        timezone=MOSCOW_TZ,
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    scheduler.add_job(
        send_morning_briefs,
        trigger=CronTrigger(
            hour=MORNING_BRIEF_HOUR,
            minute=MORNING_BRIEF_MINUTE,
            timezone=MOSCOW_TZ,
        ),
        args=(bot,),
        id="morning_brief",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        schedule_daily_reminders,
        trigger=CronTrigger(hour=0, minute=5, timezone=MOSCOW_TZ),
        args=(scheduler, bot),
        id="schedule_day_reminders",
        replace_existing=True,
    )

    scheduler.start()
    schedule_daily_reminders(scheduler, bot)
    logger.info("Бот запущен; утренняя сводка запланирована на 08:00 МСК.")
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
