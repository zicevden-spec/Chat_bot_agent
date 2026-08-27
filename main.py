import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv
from sqlalchemy import select

from database import async_session, init_db
from models import Consent, Participation, User

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
    raise SystemExit("BOT_TOKEN не задан. Открой файл .env и вставь туда токен.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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
async def consent_yes(callback: CallbackQuery):
    async with async_session() as session:
        session.add(Consent(telegram_user_id=callback.from_user.id))
        await session.commit()

    await callback.answer("Согласие принято")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(QUESTIONS_TEXT)


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
