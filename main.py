import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.exc import InterfaceError

from admin_handlers import (
    admin_reply_kb,
    is_admin,
    is_excluded,
    router as admin_router,
    setup_admin_commands,
)
from database import async_session, init_db
from models import Admin, Consent, Participation, User

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "0"))

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

ADMIN_WELCOME_TEXT = (
    "Здравствуйте! Это администраторский режим.\n\n"
    "Нажмите кнопку «🛠 Админка» внизу экрана, чтобы открыть панель управления."
)

EXCLUDED_TEXT = (
    "Здравствуйте! Ваш аккаунт отмечен как служебный и не участвует в розыгрыше."
)

CONSENT_TEXT_PART1 = (
    "ПУБЛИЧНАЯ ОФЕРТА\n"
    "о предоставлении согласия на использование изображения (образа) "
    "и на обработку персональных данных\n\n"
    "г. Симферополь\n\n"
    "Управляющая компания «ФЦБ» (далее — «Компания»), в лице генерального директора "
    "Яурова Дениса Анатольевича, действующего на основании Устава, размещает настоящую "
    "публичную оферту (далее — «Оферта»), адресованную любому дееспособному физическому "
    "лицу (далее — «Клиент»), оставившему видеоотзыв в Telegram-боте Компании.\n\n"
    "В соответствии с п. 2 ст. 437 Гражданского кодекса Российской Федерации "
    "(далее — ГК РФ) настоящий документ является официальным предложением "
    "(публичной офертой) Компании и содержит все существенные условия предоставления "
    "Клиентом согласия, указанного в разделе 1 Оферты.\n\n"
    "1. Предмет оферты\n\n"
    "1.1. Клиент безвозмездно предоставляет Компании согласие на использование своего "
    "изображения (образа), голоса и иных сведений, содержащихся в видеоотзыве, записанном "
    "и направленном Клиентом через Telegram-бот Компании (далее — «Видеоотзыв»).\n\n"
    "1.2. Согласие предоставляется в порядке, предусмотренном ст. 152.1 ГК РФ "
    "(охрана изображения гражданина), а также, в части персональных данных, "
    "в соответствии с Федеральным законом от 27.07.2006 № 152-ФЗ «О персональных данных».\n\n"
    "1.3. Под использованием изображения (образа) понимается воспроизведение, публикация, "
    "распространение, доведение до всеобщего сведения, обнародование Видеоотзыва "
    "(полностью или в части, в том числе в виде отдельных кадров, фрагментов, "
    "а также в составе производных рекламных и информационных материалов).\n\n"
    "2. Способы и цели использования\n\n"
    "2.1. Компания вправе использовать Видеоотзыв и изображение (образ) Клиента "
    "в следующих целях: информирование о деятельности Компании, продвижение услуг Компании, "
    "формирование положительной деловой репутации, размещение отзывов клиентов.\n\n"
    "2.2. Использование осуществляется путём размещения Видеоотзыва:\n"
    "• в официальных аккаунтах и на страницах Компании в социальных сетях, мессенджерах "
    "и на видеохостингах;\n"
    "• в личных (персональных) аккаунтах и на страницах представителей и сотрудников Компании "
    "в социальных сетях и мессенджерах;\n"
    "• на официальном сайте Компании, в рекламных и презентационных материалах Компании.\n\n"
    "2.3. Согласие даётся без ограничения территории и с правом использования на территории "
    "Российской Федерации и за её пределами (с учётом доступности сети «Интернет»).\n\n"
    "3. Обработка персональных данных\n\n"
    "3.1. Клиент даёт согласие на обработку Компанией персональных данных, содержащихся "
    "в Видеоотзыве, включая изображение, голос, а также имя (никнейм), сообщённые Клиентом "
    "сведения. Изображение и голос могут относиться к биометрическим персональным данным.\n\n"
    "3.2. Обработка включает сбор, запись, систематизацию, хранение, использование, "
    "распространение (публикацию), обезличивание, удаление персональных данных "
    "как с использованием средств автоматизации, так и без таковых.\n\n"
    "3.3. Согласие действует со дня акцепта Оферты в течение срока, необходимого "
    "для достижения целей обработки, и может быть отозвано Клиентом в порядке п. 5.2 Оферты."
)

CONSENT_TEXT_PART2 = (
    "4. Акцепт оферты\n\n"
    "4.1. Акцептом настоящей Оферты (полным и безоговорочным принятием её условий) "
    "в соответствии с п. 1 и п. 3 ст. 438 ГК РФ является совершение Клиентом конклюдентного "
    "действия — записи и отправки Видеоотзыва через Telegram-бот Компании после ознакомления "
    "с текстом настоящей Оферты.\n\n"
    "4.2. Совершая акцепт, Клиент подтверждает, что он является совершеннолетним "
    "и дееспособным, действует добровольно, ознакомлен с условиями Оферты "
    "и согласен с ними в полном объёме.\n\n"
    "4.3. Согласие предоставляется на безвозмездной основе; вознаграждение (плата) "
    "за использование изображения и Видеоотзыва Клиенту не выплачивается.\n\n"
    "5. Срок действия и отзыв согласия\n\n"
    "5.1. Согласие предоставляется на неопределённый срок и действует до его отзыва Клиентом.\n\n"
    "5.2. Клиент вправе отозвать согласие, направив в Компанию письменное заявление "
    "на юридический адрес Компании либо обращение через Telegram-бот Компании. "
    "Компания прекращает дальнейшее использование Видеоотзыва и удаляет опубликованные "
    "материалы, находящиеся под её контролем, в разумный срок, не превышающий 30 (тридцати) "
    "календарных дней с момента получения отзыва.\n\n"
    "5.3. Отзыв согласия не влечёт обязанности Компании изъять материалы, которые были "
    "правомерно скопированы, распространены или сохранены третьими лицами до момента отзыва "
    "и находятся вне контроля Компании.\n\n"
    "6. Реквизиты Компании\n\n"
    "Управляющая компания «ФЦБ»\n"
    "ОГРН: 1219100011327\n"
    "КПП: 910201001\n"
    "Юридический адрес: 295011, Республика Крым, г. Симферополь, пр-кт Кирова, д. 30/2\n"
    "Генеральный директор: Яуров Денис Анатольевич"
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
        select(func.max(Participation.ticket_number))
        .where(
            Participation.period_year == year,
            Participation.period_month == month,
        )
    )
    max_ticket = result.scalar_one_or_none()
    if max_ticket is None:
        next_num = 1
    else:
        try:
            last_part = max_ticket.split("-")[-1]
            next_num = int(last_part) + 1
        except (ValueError, IndexError):
            next_num = 1
    return f"{year}-{month:02d}-A-{next_num:04d}"


async def ensure_super_admin():
    if SUPER_ADMIN_ID == 0:
        return

    for attempt in range(3):
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(Admin).where(Admin.telegram_user_id == SUPER_ADMIN_ID)
                )
                admin = result.scalar_one_or_none()
                if admin is None:
                    session.add(Admin(telegram_user_id=SUPER_ADMIN_ID, role="superadmin"))
                    await session.commit()
                    logging.info(f"Super admin {SUPER_ADMIN_ID} added to database")
            await setup_admin_commands(bot, SUPER_ADMIN_ID)
            return
        except InterfaceError as e:
            logging.warning(f"Database connection error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(2)
            else:
                logging.error("Failed to ensure super admin after 3 attempts")
        except Exception as e:
            logging.error(f"Unexpected error ensuring super admin: {e}")
            return


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await get_or_create_user(message)

    if await is_admin(message.from_user.id):
        await message.answer(ADMIN_WELCOME_TEXT, reply_markup=admin_reply_kb)
        return

    if await is_excluded(message.from_user.id):
        await message.answer(EXCLUDED_TEXT, reply_markup=ReplyKeyboardRemove())
        return

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
            "Спасибо за ваш отзыв!",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await message.answer(WELCOME_TEXT, reply_markup=read_consent_kb)


@dp.callback_query(F.data == "read_consent")
async def read_consent(callback: CallbackQuery):
    if await is_admin(callback.from_user.id) or await is_excluded(callback.from_user.id):
        await callback.answer("Ваш аккаунт не участвует в розыгрыше", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(CONSENT_TEXT_PART1)
    await callback.message.answer(CONSENT_TEXT_PART2, reply_markup=consent_kb)


@dp.callback_query(F.data == "consent_yes")
async def consent_yes(callback: CallbackQuery, state: FSMContext):
    if await is_admin(callback.from_user.id) or await is_excluded(callback.from_user.id):
        await callback.answer("Ваш аккаунт не участвует в розыгрыше", show_alert=True)
        await state.clear()
        return

    async with async_session() as session:
        session.add(
            Consent(
                telegram_user_id=callback.from_user.id,
                consent_version="offer_v1",
            )
        )
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
    if await is_admin(callback.from_user.id):
        await callback.answer("Админы не участвуют в розыгрыше", show_alert=True)
        await state.clear()
        return
    if await is_excluded(callback.from_user.id):
        await callback.answer("Ваш аккаунт исключён из розыгрыша", show_alert=True)
        await state.clear()
        return

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


async def main():
    try:
        await init_db()
        await ensure_super_admin()
    except Exception as e:
        logging.error(f"Error during startup: {e}")
    
    logging.info("Starting bot polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
