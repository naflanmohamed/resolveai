from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .core import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(250))
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), default="text")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    document: Mapped[Document] = relationship(back_populates="chunks")


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(250))
    customer_name: Mapped[str] = mapped_column(String(120))
    customer_email: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    category: Mapped[str] = mapped_column(String(40), default="General")
    priority: Mapped[str] = mapped_column(String(20), default="Medium")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    draft_response: Mapped[str] = mapped_column(Text, default="")
    approved_response: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    generated_with: Mapped[str] = mapped_column(String(30), default="local")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(90))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[User | None] = relationship()
