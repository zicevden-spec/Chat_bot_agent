from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from database import async_session
from models import Admin, ExcludedUser, Participation, User

router = Router()

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

STATUS_EMOJI = {"active": "✅", "disqualified": "❌", "winner": "🏆"}

admin_menu_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Участники", callback_data="admin_participants")],
        [InlineKeyboardButton(text="🎲 Провести розыгрыш", callback_data="admin_draw")],
        [InlineKeyboardButton(text="🚫 Исключения", callback_data="admin_exclusions")],
        [InlineKeyboardButton(text="👤 Управление админами", callback_data="admin_manage_admins")],
    ]
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


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Команда не найдена.")
        return
    await message.answer("🛠 Панель управления", reply_markup=admin_menu_kb)


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
    await callback.answer("Админ удалён")
    await callback.message.answer(f"Пользователь {target_id} больше не админ.")


@router.callback_query(F.data == "admin_draw")
async def admin_draw(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("🎲 Провести розыгрыш (в разработке)")
