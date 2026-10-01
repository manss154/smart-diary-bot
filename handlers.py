"""Кнопочные сценарии дневника и защита белого списка."""

import asyncio
import logging
import uuid
from datetime import datetime

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import ALLOWED_USER_IDS, MOSCOW_TZ, VOICE_NOTES_DIR
from database import (
    add_calories,
    add_task,
    add_voice_note,
    complete_task,
    get_daily_calories,
    get_tasks,
    register_user,
)
from smiles_and_quotes import random_morning_quote
from visualizer import create_weekly_chart

logger = logging.getLogger(__name__)
router = Router(name="diary")
UNKNOWN_USER_TEXT = "Слушай, ты кто такой, дорогой? Я тебя не знаю. Иди своей дорогой, не мешай делу!"


class DiaryStates(StatesGroup):
    """Состояния пошагового ввода задачи и калорий."""

    waiting_for_task_title = State()
    waiting_for_calories = State()


class AccessMiddleware(BaseMiddleware):
    """Отсекает неразрешённые сообщения и нажатия до вызова обработчиков."""

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None or user.id not in ALLOWED_USER_IDS:
            if isinstance(event, Message):
                await event.answer(UNKNOWN_USER_TEXT)
            elif isinstance(event, CallbackQuery):
                await event.answer(UNKNOWN_USER_TEXT, show_alert=True)
            return None
        return await handler(event, data)


router.message.outer_middleware(AccessMiddleware())
router.callback_query.outer_middleware(AccessMiddleware())


def main_menu() -> InlineKeyboardMarkup:
    """Собирает основную клавиатуру дневника."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Задачи на сегодня", callback_data="tasks:today")],
            [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="task:add")],
            [InlineKeyboardButton(text="🍽 Записать калории", callback_data="calories:add")],
            [InlineKeyboardButton(text="📈 Итоги недели", callback_data="chart:week")],
        ]
    )


def cancel_menu() -> InlineKeyboardMarkup:
    """Клавиатура отмены текущего ввода."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")]]
    )


def category_menu() -> InlineKeyboardMarkup:
    """Клавиатура выбора категории новой задачи."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Рабочие", callback_data="task:category:work")],
            [InlineKeyboardButton(text="Личные", callback_data="task:category:personal")],
            [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")],
        ]
    )


def task_list_menu(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Формирует текст и кнопки задач за сегодняшний день."""
    tasks = get_tasks(user_id)
    keyboard: list[list[InlineKeyboardButton]] = []
    lines = ["Задачи на сегодня:"]
    for task in tasks:
        done = task["completed_at"] is not None
        marker = "✅" if done else "▫️"
        lines.append(f"{marker} {task['category']}: {task['title']}")
        if not done:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=f"Выполнено: {task['title'][:35]}",
                        callback_data=f"task:done:{task['id']}",
                    )
                ]
            )
    if not tasks:
        lines.append("Пока пусто. Добавь первую задачу.")
    keyboard.append([InlineKeyboardButton(text="В меню", callback_data="menu:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    """Регистрирует разрешённого пользователя и показывает главное меню."""
    await state.clear()
    register_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "Дневник готов. Выбирай, что сегодня двигаем вперёд.",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "menu:main")
async def menu_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Возвращает пользователя в главное меню."""
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Главное меню. Выбирай следующий шаг.", reply_markup=main_menu()
        )


@router.callback_query(F.data == "tasks:today")
async def tasks_handler(callback: CallbackQuery) -> None:
    """Показывает сегодняшние задачи и кнопки их завершения."""
    await callback.answer()
    if callback.message:
        text, keyboard = task_list_menu(callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "task:add")
async def add_task_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Предлагает выбрать категорию новой задачи."""
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text("К какой категории относится задача?", reply_markup=category_menu())


@router.callback_query(F.data.startswith("task:category:"))
async def task_category_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Запоминает категорию и переходит к вводу названия задачи."""
    category = "Рабочие" if callback.data.endswith(":work") else "Личные"
    await state.update_data(task_category=category)
    await state.set_state(DiaryStates.waiting_for_task_title)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            f"Напиши задачу в категории «{category}».", reply_markup=cancel_menu()
        )


@router.message(DiaryStates.waiting_for_task_title, F.text)
async def save_task_handler(message: Message, state: FSMContext) -> None:
    """Сохраняет введённую задачу на текущий день."""
    title = (message.text or "").strip()
    if not title or len(title) > 200:
        await message.answer("Название должно содержать от 1 до 200 символов.", reply_markup=cancel_menu())
        return
    data = await state.get_data()
    add_task(message.from_user.id, title, data["task_category"])
    await state.clear()
    await message.answer(f"Добавлено: {title}", reply_markup=main_menu())


@router.callback_query(F.data.startswith("task:done:"))
async def complete_task_handler(callback: CallbackQuery) -> None:
    """Завершает только задачу, принадлежащую нажавшему пользователю."""
    task_id = int(callback.data.rsplit(":", maxsplit=1)[1])
    changed = complete_task(callback.from_user.id, task_id)
    await callback.answer("Задача выполнена." if changed else "Задача уже отмечена или не найдена.")
    if callback.message:
        text, keyboard = task_list_menu(callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "calories:add")
async def calories_prompt_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Запускает ввод съеденных калорий."""
    await state.clear()
    await state.set_state(DiaryStates.waiting_for_calories)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Введи количество калорий числом.", reply_markup=cancel_menu()
        )


@router.message(DiaryStates.waiting_for_calories, F.text)
async def save_calories_handler(message: Message, state: FSMContext) -> None:
    """Проверяет число и сохраняет запись о калориях."""
    value = (message.text or "").strip()
    if not value.isdecimal() or not 1 <= int(value) <= 10000:
        await message.answer("Введи целое число от 1 до 10000.", reply_markup=cancel_menu())
        return
    amount = int(value)
    add_calories(message.from_user.id, amount)
    total = get_daily_calories(message.from_user.id)
    await state.clear()
    await message.answer(
        f"Записал {amount} ккал. Всего сегодня: {total} ккал.", reply_markup=main_menu()
    )


@router.message(F.voice)
async def voice_note_handler(message: Message) -> None:
    """Скачивает голосовое сообщение в дневную папку и записывает его в SQLite."""
    now = datetime.now(MOSCOW_TZ)
    user_dir = VOICE_NOTES_DIR / str(message.from_user.id) / now.date().isoformat()
    user_dir.mkdir(parents=True, exist_ok=True)
    voice_path = user_dir / f"{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}.ogg"
    try:
        await message.bot.download(message.voice, destination=voice_path)
        add_voice_note(message.from_user.id, str(voice_path), now.date())
    except Exception:
        logger.exception("Не удалось сохранить голосовую заметку для пользователя %s", message.from_user.id)
        await message.answer("Не удалось сохранить голосовую заметку. Попробуй ещё раз.")
        return
    await message.answer("Голосовая заметка сохранена в дневнике.", reply_markup=main_menu())


@router.callback_query(F.data == "chart:week")
async def weekly_chart_handler(callback: CallbackQuery) -> None:
    """Строит недельный график, не блокируя обработку других обновлений."""
    await callback.answer("Готовлю график…")
    try:
        chart_path = await asyncio.to_thread(create_weekly_chart, callback.from_user.id)
        if callback.message:
            await callback.message.answer_photo(
                photo=FSInputFile(chart_path),
                caption="Твои итоги за последние семь дней.",
                reply_markup=main_menu(),
            )
    except Exception:
        logger.exception("Не удалось построить недельный график для пользователя %s", callback.from_user.id)
        if callback.message:
            await callback.message.answer("Не удалось построить график. Попробуй позже.")


@router.callback_query(F.data == "flow:cancel")
async def cancel_flow_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Отменяет текущий ввод и возвращает главное меню."""
    await state.clear()
    await callback.answer("Ввод отменён.")
    if callback.message:
        await callback.message.edit_text("Главное меню.", reply_markup=main_menu())


async def send_morning_brief(bot, user_id: int) -> None:
    """Отправляет пользователю сводку задач и калорий за сегодня."""
    register_user(user_id, None)
    tasks = get_tasks(user_id)
    if tasks:
        task_lines = [
            f"{'✅' if task['completed_at'] else '▫️'} {task['category']}: {task['title']}"
            for task in tasks
        ]
        task_text = "\n".join(task_lines)
    else:
        task_text = "Задач на сегодня пока нет. Добавь первую через меню."
    calories = get_daily_calories(user_id)
    await bot.send_message(
        user_id,
        f"Доброе утро!\n\nЗадачи на сегодня:\n{task_text}\n\n"
        f"Калории за сегодня: {calories} ккал.\n\n{random_morning_quote()}",
        reply_markup=main_menu(),
    )
