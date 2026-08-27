import secrets
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import func, select

from database import async_session
from models import Admin, Consent, Draw, ExcludedUser, Participation, User, Winner

router = Router()

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

STATUS_EMOJI = {"active": "✅", "disqualified": "❌", "winner": "🏆"}
PRIZES = {1: 5000, 2: 3000, 3: 2000}

admin_menu_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Участники", callback_data="admin_participants")],
        [InlineKeyboardButton(text="🎲 Провести розыгрыш", callback_data="admin_draw")],
        [InlineKeyboardButton(text="🚫 Исключения", callback_data="admin_exclusions")],
        [InlineKeyboardButton(text="👤 Управление админами", callback_data="admin_manage_admins")],
    ]
)

admin_reply_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🛠 Админка")]],
    resize_keyboard=True,
    is_persistent=True,
)

back_kb_row = [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]


class AdminState(StatesGroup):
    waiting_exclusion_id = State()
    waiting_exclusion_reason = State()
    waiting_admin_id = State()
    waiting_admin_role = State()
    waiting_disqualify_reason = State()


def month_name(month: int) -> str:
    return MONTHS_RU[month - 1]


async def get_admin(telegram_user_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()


async def is_admin(telegram_user_id: int) -> bool:
    return await get_admin(telegram_user_id) is not None


async def is_excluded(telegram_user_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(ExcludedUser).where(ExcludedUser.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none() is not None


async def setup_admin_commands(bot, telegram_user_id: int):
    try:
        await bot.set_my_commands(
            [BotCommand(command="admin", description="🛠 Панель управления")],
            scope=BotCommandScopeChat(chat_id=telegram_user_id),
        )
    except Exception:
        pass


async def reset_admin_commands(bot, telegram_user_id: int):
    try:
        await bot.set_my_commands([], scope=BotCommandScopeChat(chat_id=telegram_user_id))
    except Exception:
        pass


async def get_eligible_participants(session, year: int, month: int):
    result = await session.execute(
        select(Participation, User)
        .outerjoin(User, User.telegram_user_id == Participation.telegram_user_id)
        .where(Participation.status == "active")
    )
    all_rows = result.all()

    eligible = []
    for p, u in all_rows:
        if (p.period_year, p.period_month) > (year, month):
            continue
        if await is_admin(p.telegram_user_id):
            continue
        if await is_excluded(p.telegram_user_id):
            continue
        eligible.append((p, u))
    return eligible


async def show_admin_panel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Панель управления", reply_markup=admin_menu_kb)


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("Команда не найдена.")
        return
    await show_admin_panel(message, state)


@router.message(F.text == "🛠 Админка")
async def admin_button(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await show_admin_panel(message, state)


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("🛠 Панель управления", reply_markup=admin_menu_kb)


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    now = datetime.now()
    async with async_session() as session:
        total = (await session.execute(
            select(func.count()).select_from(Participation)
        )).scalar_one()
        current_month = (await session.execute(
            select(func.count()).select_from(Participation).where(
                Participation.period_year == now.year,
                Participation.period_month == now.month,
            )
        )).scalar_one()
        active = (await session.execute(
            select(func.count()).select_from(Participation).where(
                Participation.status == "active"
            )
        )).scalar_one()
        excluded = (await session.execute(
            select(func.count()).select_from(ExcludedUser)
        )).scalar_one()
        admins = (await session.execute(
            select(func.count()).select_from(Admin)
        )).scalar_one()

    await callback.answer()
    await callback.message.answer(
        "📊 Статистика\n\n"
        f"Всего билетов за всё время: {total}\n"
        f"Билетов в этом месяце: {current_month}\n"
        f"Активных билетов: {active}\n"
        f"Исключённых пользователей: {excluded}\n"
        f"Админов: {admins}\n"
    )


@router.callback_query(F.data == "admin_participants")
async def admin_participants(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await state.clear()
    async with async_session() as session:
        result = await session.execute(
            select(
                Participation.period_year,
                Participation.period_month,
                func.count(),
            )
            .group_by(Participation.period_year, Participation.period_month)
            .order_by(Participation.period_year.desc(), Participation.period_month.desc())
        )
        rows = result.all()
    if not rows:
        await callback.answer("Участников пока нет", show_alert=True)
        return
    buttons = [
        [InlineKeyboardButton(
            text=f"{month_name(m)} {y} - {c} чел.",
            callback_data=f"part_period:{y}:{m}",
        )]
        for y, m, c in rows
    ]
    buttons.append(back_kb_row)
    await callback.answer()
    await callback.message.answer(
        "👥 Участники\n\nВыберите период:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("part_period:"))
async def part_period(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    _, y, m = callback.data.split(":")
    year, month = int(y), int(m)
    async with async_session() as session:
        result = await session.execute(
            select(Participation, User)
            .outerjoin(User, User.telegram_user_id == Participation.telegram_user_id)
            .where(Participation.period_year == year, Participation.period_month == month)
            .order_by(Participation.id)
        )
        rows = result.all()
    buttons = []
    for p, u in rows:
        name = u.first_name if u is not None else "Неизвестно"
        emoji = STATUS_EMOJI.get(p.status, "")
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {p.ticket_number} - {name}",
            callback_data=f"part_user:{p.id}",
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ К периодам", callback_data="admin_participants")])
    await callback.answer()
    await callback.message.answer(
        f"👥 Участники за {month_name(month)} {year} (нажмите на участника):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("part_user:"))
async def part_user(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    part_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        result = await session.execute(
            select(Participation, User)
            .outerjoin(User, User.telegram_user_id == Participation.telegram_user_id)
            .where(Participation.id == part_id)
        )
        row = result.first()
    if row is None:
        await callback.answer("Участие не найдено", show_alert=True)
        return
    p, u = row
    name = f"{u.first_name or ''} {u.last_name or ''}".strip() if u is not None else "Неизвестно"
    username = f"@{u.username}" if u is not None and u.username else "нет"
    status_ru = {"active": "активен", "disqualified": "дисквалифицирован", "winner": "победитель"}.get(p.status, p.status)

    buttons = [
        [InlineKeyboardButton(text="▶️ Показать видео", callback_data=f"part_video:{p.id}")],
    ]
    if p.status == "active":
        buttons.append([InlineKeyboardButton(text="❌ Дисквалифицировать", callback_data=f"part_disq:{p.id}")])
    if p.status == "disqualified":
        buttons.append([InlineKeyboardButton(text="✅ Вернуть в розыгрыш", callback_data=f"part_requal:{p.id}")])
    buttons.append([InlineKeyboardButton(text="🗑 Удалить из базы", callback_data=f"part_del_ask:{p.id}")])
    buttons.append([InlineKeyboardButton(
        text="⬅️ К списку",
        callback_data=f"part_period:{p.period_year}:{p.period_month}",
    )])

    text = (
        f"🎫 Билет: {p.ticket_number}\n"
        f"Имя: {name}\n"
        f"Username: {username}\n"
        f"Telegram ID: {p.telegram_user_id}\n"
        f"Дата: {p.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"Статус: {status_ru}\n"
    )
    if p.status == "disqualified":
        text += f"Причина: {p.disqualify_reason or 'не указана'}\n"

    await callback.answer()
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("part_video:"))
async def part_video(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    part_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        p = (await session.execute(
            select(Participation).where(Participation.id == part_id)
        )).scalar_one_or_none()
    if p is None:
        await callback.answer("Участие не найдено", show_alert=True)
        return
    await callback.answer("Отправляю видео")
    await callback.message.answer_video_note(p.video_file_id)


@router.callback_query(F.data.startswith("part_disq:"))
async def part_disq(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    part_id = int(callback.data.split(":")[1])
    await state.update_data(disq_part_id=part_id)
    await state.set_state(AdminState.waiting_disqualify_reason)
    await callback.answer()
    await callback.message.answer("Укажите причину дисквалификации.")


@router.message(AdminState.waiting_disqualify_reason)
async def disq_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    part_id = data.get("disq_part_id")
    async with async_session() as session:
        p = (await session.execute(
            select(Participation).where(Participation.id == part_id)
        )).scalar_one_or_none()
        if p is None:
            await message.answer("Участие не найдено.")
            await state.clear()
            return
        if p.status == "winner":
            await message.answer("Победителя нельзя дисквалифицировать.")
            await state.clear()
            return
        p.status = "disqualified"
        p.disqualified_by = message.from_user.id
        p.disqualified_at = datetime.now()
        p.disqualify_reason = message.text
        await session.commit()
        ticket = p.ticket_number
    await message.answer(f"Участник {ticket} дисквалифицирован.")
    await state.clear()


@router.callback_query(F.data.startswith("part_requal:"))
async def part_requal(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    part_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        p = (await session.execute(
            select(Participation).where(Participation.id == part_id)
        )).scalar_one_or_none()
        if p is None:
            await callback.answer("Участие не найдено", show_alert=True)
            return
        p.status = "active"
        p.disqualified_by = None
        p.disqualified_at = None
        p.disqualify_reason = None
        await session.commit()
        ticket = p.ticket_number
    await callback.answer("Возвращён в розыгрыш")
    await callback.message.answer(f"Участник {ticket} снова участвует в розыгрыше.")


@router.callback_query(F.data.startswith("part_del_ask:"))
async def part_del_ask(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    part_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ Да, удалить полностью", callback_data=f"part_del_yes:{part_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"part_user:{part_id}")],
        ]
    )
    await callback.answer()
    await callback.message.answer(
        "⚠️ ВНИМАНИЕ!\n\n"
        "Будут полностью удалены из базы:\n"
        "- пользователь\n"
        "- все его участия и билеты\n"
        "- согласия\n"
        "- записи о победах\n\n"
        "Действие необратимо. Подтвердите удаление.",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("part_del_yes:"))
async def part_del_yes(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    part_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        p = (await session.execute(
            select(Participation).where(Participation.id == part_id)
        )).scalar_one_or_none()
        if p is None:
            await callback.answer("Участие не найдено", show_alert=True)
            return
        uid = p.telegram_user_id

        parts = (await session.execute(
            select(Participation).where(Participation.telegram_user_id == uid)
        )).scalars().all()
        part_ids = [x.id for x in parts]

        winners = (await session.execute(
            select(Winner).where(Winner.participation_id.in_(part_ids))
        )).scalars().all()
        for w in winners:
            await session.delete(w)
        for x in parts:
            await session.delete(x)

        consents = (await session.execute(
            select(Consent).where(Consent.telegram_user_id == uid)
        )).scalars().all()
        for c in consents:
            await session.delete(c)

        u = (await session.execute(
            select(User).where(User.telegram_user_id == uid)
        )).scalar_one_or_none()
        if u is not None:
            await session.delete(u)

        await session.commit()
    await callback.answer("Клиент удалён из базы")
    await callback.message.answer(
        f"Клиент с Telegram ID {uid} полностью удалён из базы данных."
    )


@router.callback_query(F.data == "admin_exclusions")
async def admin_exclusions(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить исключение", callback_data="excl_add")],
            [InlineKeyboardButton(text="🗑 Удалить исключение", callback_data="excl_list")],
            back_kb_row,
        ]
    )
    await callback.answer()
    await callback.message.answer(
        "🚫 Исключения\n\n"
        "Сюда добавляются сотрудники и тестовые аккаунты. "
        "Они не участвуют в розыгрыше.",
        reply_markup=kb,
    )


@router.callback_query(F.data == "excl_add")
async def excl_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminState.waiting_exclusion_id)
    await callback.answer()
    await callback.message.answer(
        "Отправьте Telegram ID пользователя, которого нужно исключить из розыгрыша."
    )


@router.message(AdminState.waiting_exclusion_id)
async def excl_id(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Это не похоже на числовой ID. Попробуйте ещё раз.")
        return
    await state.update_data(exclusion_id=int(text))
    await state.set_state(AdminState.waiting_exclusion_reason)
    await message.answer("Укажите причину исключения.")


@router.message(AdminState.waiting_exclusion_reason)
async def excl_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("exclusion_id")
    async with async_session() as session:
        result = await session.execute(
            select(ExcludedUser).where(ExcludedUser.telegram_user_id == target_id)
        )
        if result.scalar_one_or_none() is not None:
            await message.answer("Этот пользователь уже в списке исключений.")
        else:
            session.add(
                ExcludedUser(
                    telegram_user_id=target_id,
                    reason=message.text,
                    added_by=message.from_user.id,
                )
            )
            await session.commit()
            await message.answer(
                f"Пользователь {target_id} добавлен в исключения.\nПричина: {message.text}"
            )
    await state.clear()


@router.callback_query(F.data == "excl_list")
async def excl_list(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(ExcludedUser))
        items = result.scalars().all()
    if not items:
        await callback.answer("Список исключений пуст", show_alert=True)
        return
    buttons = [
        [InlineKeyboardButton(
            text=f"{i.telegram_user_id} - {i.reason or 'без причины'}",
            callback_data=f"excl_del:{i.telegram_user_id}",
        )]
        for i in items
    ]
    buttons.append(back_kb_row)
    await callback.answer()
    await callback.message.answer(
        "🚫 Исключённые пользователи (нажмите, чтобы удалить):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("excl_del:"))
async def excl_del(callback: CallbackQuery):
    target_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        result = await session.execute(
            select(ExcludedUser).where(ExcludedUser.telegram_user_id == target_id)
        )
        item = result.scalar_one_or_none()
        if item is not None:
            await session.delete(item)
            await session.commit()
    await callback.answer("Удалено из исключений")
    await callback.message.answer(f"Пользователь {target_id} удалён из исключений.")


@router.callback_query(F.data == "admin_manage_admins")
async def admin_manage_admins(callback: CallbackQuery, state: FSMContext):
    admin = await get_admin(callback.from_user.id)
    if admin is None or admin.role != "superadmin":
        await callback.answer("Доступно только супер-админу", show_alert=True)
        return
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add")],
            [InlineKeyboardButton(text="🗑 Удалить админа", callback_data="admin_list")],
            back_kb_row,
        ]
    )
    await callback.answer()
    await callback.message.answer(
        "👤 Управление админами\n\n"
        "Админ - видит статистику, участников, может проводить розыгрыш.\n"
        "Супер-админ - всё то же самое плюс управление админами.",
        reply_markup=kb,
    )


@router.callback_query(F.data == "admin_add")
async def admin_add(callback: CallbackQuery, state: FSMContext):
    admin = await get_admin(callback.from_user.id)
    if admin is None or admin.role != "superadmin":
        await callback.answer("Доступно только супер-админу", show_alert=True)
        return
    await state.set_state(AdminState.waiting_admin_id)
    await callback.answer()
    await callback.message.answer("Отправьте Telegram ID нового админа.")


@router.message(AdminState.waiting_admin_id)
async def admin_add_id(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Это не похоже на числовой ID. Попробуйте ещё раз.")
        return
    await state.update_data(new_admin_id=int(text))
    await state.set_state(AdminState.waiting_admin_role)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Админ", callback_data="admin_role:admin")],
            [InlineKeyboardButton(text="Супер-админ", callback_data="admin_role:superadmin")],
        ]
    )
    await message.answer("Какую роль выдать пользователю?", reply_markup=kb)


@router.message(AdminState.waiting_admin_role)
async def admin_role_hint(message: Message):
    await message.answer("Нажмите кнопку под предыдущим сообщением: Админ или Супер-админ.")


@router.callback_query(F.data.startswith("admin_role:"))
async def admin_role(callback: CallbackQuery, state: FSMContext):
    admin = await get_admin(callback.from_user.id)
    if admin is None or admin.role != "superadmin":
        await callback.answer("Доступно только супер-админу", show_alert=True)
        return
    data = await state.get_data()
    target_id = data.get("new_admin_id")
    if target_id is None:
        await callback.answer("Не удалось получить ID. Начните заново.", show_alert=True)
        await state.clear()
        return
    role = callback.data.split(":")[1]
    async with async_session() as session:
        result = await session.execute(select(Admin).where(Admin.telegram_user_id == target_id))
        if result.scalar_one_or_none() is not None:
            await callback.answer("Этот пользователь уже админ", show_alert=True)
        else:
            session.add(Admin(telegram_user_id=target_id, role=role, added_by=callback.from_user.id))
            await session.commit()
            await callback.message.answer(
                f"Пользователь {target_id} добавлен с ролью «{role}»."
            )
            await setup_admin_commands(callback.bot, target_id)
            try:
                await callback.bot.send_message(
                    target_id,
                    "🎉 Вам выданы права админа в боте розыгрыша.\n\n"
                    "Откройте бота и нажмите /start - "
                    "внизу появится кнопка «🛠 Админка».",
                )
            except Exception:
                pass
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "admin_list")
async def admin_list(callback: CallbackQuery):
    admin = await get_admin(callback.from_user.id)
    if admin is None or admin.role != "superadmin":
        await callback.answer("Доступно только супер-админу", show_alert=True)
        return
    async with async_session() as session:
        result = await session.execute(select(Admin))
        items = result.scalars().all()
    buttons = []
    for i in items:
        if i.telegram_user_id == callback.from_user.id:
            continue
        role_ru = "супер-админ" if i.role == "superadmin" else "админ"
        buttons.append([InlineKeyboardButton(
            text=f"Удалить: {i.telegram_user_id} ({role_ru})",
            callback_data=f"admin_del:{i.telegram_user_id}",
        )])
    if not buttons:
        await callback.answer("Других админов пока нет", show_alert=True)
        return
    buttons.append(back_kb_row)
    await callback.answer()
    await callback.message.answer(
        "👤 Админы (нажмите, чтобы удалить):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("admin_del:"))
async def admin_del(callback: CallbackQuery):
    admin = await get_admin(callback.from_user.id)
    if admin is None or admin.role != "superadmin":
        await callback.answer("Доступно только супер-админу", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    if target_id == callback.from_user.id:
        await callback.answer("Нельзя удалить самого себя", show_alert=True)
        return
    async with async_session() as session:
        target = (await session.execute(
            select(Admin).where(Admin.telegram_user_id == target_id)
        )).scalar_one_or_none()
        if target is None:
            await callback.answer("Админ не найден", show_alert=True)
            return
        if target.role == "superadmin":
            supers = (await session.execute(
                select(func.count()).select_from(Admin).where(Admin.role == "superadmin")
            )).scalar_one()
            if supers <= 1:
                await callback.answer("Нельзя удалить последнего супер-админа", show_alert=True)
                return
        await session.delete(target)
        await session.commit()
    await reset_admin_commands(callback.bot, target_id)
    await callback.answer("Админ удалён")
    await callback.message.answer(f"Пользователь {target_id} больше не админ.")


# ========== РОЗЫГРЫШ ==========


@router.callback_query(F.data == "admin_draw")
async def admin_draw(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    now = datetime.now()
    async with async_session() as session:
        result = await session.execute(
            select(
                Participation.period_year,
                Participation.period_month,
                func.count(),
            )
            .group_by(Participation.period_year, Participation.period_month)
            .order_by(Participation.period_year.desc(), Participation.period_month.desc())
        )
        rows = result.all()

    periods = set((y, m) for y, m, _ in rows)
    periods.add((now.year, now.month))
    periods = sorted(periods, reverse=True)

    buttons = [
        [InlineKeyboardButton(
            text=f"{month_name(m)} {y}",
            callback_data=f"draw_select:{y}:{m}",
        )]
        for y, m in periods
    ]
    buttons.append(back_kb_row)

    await callback.answer()
    await callback.message.answer(
        "🎲 Провести розыгрыш\n\nВыберите период:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("draw_select:"))
async def draw_select(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    _, y, m = callback.data.split(":")
    year, month = int(y), int(m)

    async with async_session() as session:
        existing = (await session.execute(
            select(Draw).where(
                Draw.period_year == year,
                Draw.period_month == month,
                Draw.status == "completed",
            )
        )).scalar_one_or_none()

    if existing is not None:
        await callback.answer(
            f"Розыгрыш за {month_name(month)} {year} уже проведён",
            show_alert=True,
        )
        return

    async with async_session() as session:
        eligible = await get_eligible_participants(session, year, month)

    count = len(eligible)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"✅ Провести розыгрыш ({count} чел.)" if count >= 3 else f"⚠️ Недостаточно участников ({count} чел.)",
                callback_data=f"draw_confirm:{year}:{month}",
            )],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_draw")],
        ]
    )

    await callback.answer()
    await callback.message.answer(
        f"🎲 Розыгрыш за {month_name(month)} {year}\n\n"
        f"Eligible участников: {count}\n"
        f"(включая перенесённых с прошлых месяцев)\n\n"
        f"Призы:\n"
        f"🥇 1 место - 5 000 руб.\n"
        f"🥈 2 место - 3 000 руб.\n"
        f"🥉 3 место - 2 000 руб.\n\n"
        + ("Можно проводить розыгрыш." if count >= 3 else
           "Недостаточно участников (нужно минимум 3).\n"
           "Участники останутся активными и попадут в следующий розыгрыш."),
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("draw_confirm:"))
async def draw_confirm(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    _, y, m = callback.data.split(":")
    year, month = int(y), int(m)

    async with async_session() as session:
        existing = (await session.execute(
            select(Draw).where(
                Draw.period_year == year,
                Draw.period_month == month,
                Draw.status == "completed",
            )
        )).scalar_one_or_none()
        if existing is not None:
            await callback.answer("Розыгрыш уже был проведён", show_alert=True)
            return

        eligible = await get_eligible_participants(session, year, month)
        count = len(eligible)

        if count < 3:
            session.add(Draw(
                period_year=year,
                period_month=month,
                created_by=callback.from_user.id,
                participants_count=count,
                status="failed_min_participants",
            ))
            await session.commit()

            await callback.answer()
            await callback.message.answer(
                f"❌ Розыгрыш за {month_name(month)} {year} НЕ проведён.\n\n"
                f"Активных участников: {count}\n"
                f"Минимально необходимое количество: 3\n\n"
                f"Участники остаются активными и автоматически попадут в следующий розыгрыш."
            )

            admins_result = await session.execute(select(Admin))
            admins = admins_result.scalars().all()
            for admin in admins:
                if admin.telegram_user_id == callback.from_user.id:
                    continue
                try:
                    await callback.bot.send_message(
                        admin.telegram_user_id,
                        f"⚠️ Розыгрыш за {month_name(month)} {year} не проведён.\n\n"
                        f"Активных участников: {count}\n"
                        f"Минимально необходимое количество: 3\n\n"
                        f"Участники перенесены на следующий месяц."
                    )
                except Exception:
                    pass
            return

        rng = secrets.SystemRandom()
        winners = rng.sample(eligible, 3)

        draw = Draw(
            period_year=year,
            period_month=month,
            created_by=callback.from_user.id,
            participants_count=count,
            status="completed",
        )
        session.add(draw)
        await session.flush()

        results = []
        for place, (participation, user) in enumerate(winners, start=1):
            prize = PRIZES[place]
            participation.status = "winner"
            session.add(Winner(
                draw_id=draw.id,
                participation_id=participation.id,
                place=place,
                prize_amount=prize,
                notified_at=None,
            ))
            results.append((place, prize, participation, user))

        await session.commit()

    await callback.answer()
    await callback.message.answer(
        f"🎉 Розыгрыш за {month_name(month)} {year} завершён!\n\n"
        f"Победители выбраны, уведомления отправлены."
    )

    for place, prize, participation, user in results:
        place_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}[place]
        try:
            await callback.bot.send_message(
                participation.telegram_user_id,
                f"{place_emoji} Поздравляем!\n\n"
                f"Вы заняли {place} место в ежемесячном розыгрыше за видеотзыв.\n\n"
                f"Ваш билет: № {participation.ticket_number}\n"
                f"Ваш приз: {prize:,} руб.\n\n"
                f"Пожалуйста, ожидайте связи с администратором для получения приза."
            )
            async with async_session() as session:
                winner_record = (await session.execute(
                    select(Winner).where(
                        Winner.draw_id == draw.id,
                        Winner.place == place,
                    )
                )).scalar_one_or_none()
                if winner_record is not None:
                    winner_record.notified_at = datetime.now()
                    await session.commit()
        except Exception:
            pass

    report_lines = [
        f"🏆 Розыгрыш за {month_name(month)} {year} завершён.",
        f"Всего участников: {count}",
        "",
        "Победители:",
    ]
    for place, prize, participation, user in results:
        place_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}[place]
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() if user is not None else "Неизвестно"
        username = f"@{user.username}" if user is not None and user.username else "нет"
        report_lines.append(
            f"\n{place_emoji} {place} место ({prize:,} руб.):\n"
            f"Имя: {name}\n"
            f"Username: {username}\n"
            f"Telegram ID: {participation.telegram_user_id}\n"
            f"Билет: № {participation.ticket_number}"
        )
    report_lines.append("\nНеобходимо связаться с победителями для выдачи приза.")
    report_text = "\n".join(report_lines)

    async with async_session() as session:
        admins_result = await session.execute(select(Admin))
        admins = admins_result.scalars().all()

    for admin in admins:
        try:
            await callback.bot.send_message(admin.telegram_user_id, report_text)
        except Exception:
            pass
