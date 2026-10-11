from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=10, max_length=128)


class Login(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: str


class TicketCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=250)
    customer_name: str = Field(min_length=2, max_length=120)
    customer_email: str = Field(default="", max_length=255)
    message: str = Field(min_length=8, max_length=12000)


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject: str
    customer_name: str
    customer_email: str
    message: str
    status: str
    category: str
    priority: str
    confidence: float
    draft_response: str
    approved_response: str
    citations: list
    generated_with: str
    created_at: datetime
    updated_at: datetime


class Approval(BaseModel):
    response: str = Field(min_length=5, max_length=15000)


class StatusUpdate(BaseModel):
    status: Literal["open", "escalated", "resolved"]


class DocumentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=250)
    content: str = Field(min_length=40, max_length=100000)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    source_type: str
    created_at: datetime
    chunk_count: int
