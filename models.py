from datetime import datetime

from sqlalchemy import Integer, String, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    start_param: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(unique=True, index=True)
    role: Mapped[str] = mapped_column(String(50), default="admin")
    added_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(index=True)
    consent_version: Mapped[str] = mapped_column(String(50), default="placeholder_v1")
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ExcludedUser(Base):
    __tablename__ = "excluded_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(unique=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    added_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Participation(Base):
    __tablename__ = "participations"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(index=True)
    ticket_number: Mapped[str] = mapped_column(String(50), unique=True)
    video_file_id: Mapped[str] = mapped_column(Text)
    period_year: Mapped[int] = mapped_column(Integer)
    period_month: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="active")
    disqualified_by: Mapped[int | None] = mapped_column(Integer)
    disqualified_at: Mapped[datetime | None] = mapped_column(DateTime)
    disqualify_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Draw(Base):
    __tablename__ = "draws"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_year: Mapped[int] = mapped_column(Integer)
    period_month: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(Integer)
    participants_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Winner(Base):
    __tablename__ = "winners"

    id: Mapped[int] = mapped_column(primary_key=True)
    draw_id: Mapped[int] = mapped_column(Integer, index=True)
    participation_id: Mapped[int] = mapped_column(Integer, index=True)
    place: Mapped[int] = mapped_column(Integer)
    prize_amount: Mapped[int] = mapped_column(Integer)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
