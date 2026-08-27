from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from database import async_session
from models import Admin, ExcludedUser, Participation

router = Router()

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


@router.callback_query(F.data == "admin_participants")
async def admin_participants(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("👥 Участники (в разработке)")


@router.callback_query(F.data == "admin_draw")
async def admin_draw(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("🎲 Провести розыгрыш (в разработке)")
