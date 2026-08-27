import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import func, select

from admin_handlers import router as admin_router
from database import async_session, init_db
from models import Admin, Consent, Participation, User

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO)

if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
    raise SystemExit("BOT_TOKEN не задан. Открой файл .env и вставь туда токен.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(admin_router)

WELCOME_TEXT = (
    "Примите участие в ежемесячном розыгрыше!\n\n"
    "Оставьте видеотзыв о нашей работе и получите билет на розыгрыш призов.\n\n"
    "Ежемесячно разыгрываются:\n"
    "1 место - 5 000 руб.\n"
    "2 место - 3 000 руб.\n"
    "3 место - 2 000 руб."
)

CONSENT_TEXT = (
    "Согласие на участие в акции\n\n"
    "Нажимая кнопку «Я согласен», вы подтверждаете, что:\n\n"
    "- добровольно оставляете видеотзыв\n"
    "- соглашаетесь на обработку персональных данных\n"
    "- соглашаетесь с условиями проведения акции\n\n"
    "(Это временный текст. Финальный текст согласия вставим позже.)"
)

QUESTIONS_TEXT = (
    "Согласие принято.\n\n"
    "Пожалуйста, запишите кружочек до 1 минуты и ответьте в нём на 3 вопроса:\n\n"
    "1. Как вас зовут и в каком городе проходили процедуру?\n"
    "2. Что вы чувствуете после освобождения от долгов?\n"
    "3. Как проходила процедура и как оцениваете работу юристов ФЦБ?"
)

read_consent_kb = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Прочитать согласие", callback_data="read_consent")]]
)

consent_kb = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Я согласен", callback_data="consent_yes")]]
)

confirm_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Отправить на конкурс", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="Записать заново", callback_data="confirm_no")],
    ]
)


class ReviewState(StatesGroup):
    waiting_video = State()
    waiting_confirm = State()


async def get_or_create_user(message: Message):
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            start_param = None
            if message.text and len(message.text.split()) > 1:
                start_param = message.text.split(maxsplit=1)[1]
            user = User(
                telegram_user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                start_param=start_param,
            )
            session.add(user)
            await session.commit()


async def generate_ticket(session, year, month):
    result = await session.execute(
        select(func.count())
        .select_from(Participation)
        .where(
            Participation.period_year == year,
            Participation.period_month == month,
        )
    )
    count = result.scalar_one()
    return f"{year}-{month:02d}-A-{count + 1:04d}"


async def ensure_super_admin():
    if SUPER_ADMIN_ID == 0:
        return
    async with async_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.telegram_user_id == SUPER_ADMIN_ID)
        )
        admin = result.scalar_one_or_none()
        if admin is None:
            session.add(Admin(telegram_user_id=SUPER_ADMIN_ID, role="superadmin"))
            await session.commit()
            logging.info(f"Super admin {SUPER_ADMIN_ID} added to database")


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await get_or_create_user(message)

    now = datetime.now()
    async with async_session() as session:
        result = await session.execute(
            select(Participation).where(
                Participation.telegram_user_id == message.from_user.id,
                Participation.period_year == now.year,
                Participation.period_month == now.month,
            )
        )
        participation = result.scalar_one_or_none()

    if participation is not None:
        await message.answer(
            "Вы уже принимали участие в акции в этом месяце.\n\n"
            f"Ваш билет: № {participation.ticket_number}\n\n"
            "Спасибо за ваш отзыв!"
        )
        return

    await message.answer(WELCOME_TEXT, reply_markup=read_consent_kb)


@dp.callback_query(F.data == "read_consent")
async def read_consent(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(CONSENT_TEXT, reply_markup=consent_kb)


@dp.callback_query(F.data == "consent_yes")
async def consent_yes(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        session.add(Consent(telegram_user_id=callback.from_user.id))
        await session.commit()

    await callback.answer("Согласие принято")
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(ReviewState.waiting_video)
    await callback.message.answer(QUESTIONS_TEXT)


@dp.message(ReviewState.waiting_video)
async def handle_video(message: Message, state: FSMContext):
    if message.video_note is None:
        await message.answer("Пожалуйста, отправьте видеокружочек.")
        return

    await state.update_data(video_file_id=message.video_note.file_id)
    await state.set_state(ReviewState.waiting_confirm)
    await message.answer(
        "Видео получено.\n\nПроверьте его и подтвердите отправку на конкурс.",
        reply_markup=confirm_kb,
    )


@dp.message(ReviewState.waiting_confirm)
async def handle_confirm_state(message: Message):
    await message.answer(
        "Нажмите кнопку под предыдущим сообщением:\n\n"
        "Отправить на конкурс - если всё в порядке.\n"
        "Записать заново - если хотите записать новый кружочек."
    )


@dp.callback_query(F.data == "confirm_no")
async def confirm_no(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(ReviewState.waiting_video)
    await callback.message.answer("Отправьте новый видеокружочек.")


@dp.callback_query(F.data == "confirm_yes")
async def confirm_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    video_file_id = data.get("video_file_id")

    if video_file_id is None:
        await callback.answer("Видео не найдено. Запишите кружочек ещё раз.", show_alert=True)
        await state.set_state(ReviewState.waiting_video)
        return

    now = datetime.now()
    async with async_session() as session:
        result = await session.execute(
            select(Participation).where(
                Participation.telegram_user_id == callback.from_user.id,
                Participation.period_year == now.year,
                Participation.period_month == now.month,
            )
        )
        if result.scalar_one_or_none() is not None:
            await callback.answer("Вы уже участвовали в этом месяце.", show_alert=True)
            await state.clear()
            return

        ticket = await generate_ticket(session, now.year, now.month)
        session.add(
            Participation(
                telegram_user_id=callback.from_user.id,
                ticket_number=ticket,
                video_file_id=video_file_id,
                period_year=now.year,
                period_month=now.month,
            )
        )
        await session.commit()

    await callback.answer("Отзыв отправлен")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Спасибо! Ваш отзыв принят.\n\n"
        f"Ваш регистрационный номер:\n№ {ticket}\n\n"
        "Розыгрыш пройдёт в конце месяца.\n"
        "Если вы станете победителем, мы сообщим вам в этом боте."
    )
    await state.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_super_admin()
    asyncio.create_task(dp.start_polling(bot))
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
