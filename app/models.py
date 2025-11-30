# app/models.py
from typing import Optional, List
from datetime import datetime
import uuid
from sqlmodel import Field, Relationship, SQLModel

class Period(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.now)
    is_locked: bool = Field(default=False)
    ribs: List["EmployeeRib"] = Relationship(back_populates="period")
    cins: List["EmployeeCIN"] = Relationship(back_populates="period")

class Bank(SQLModel, table=True):
    code: str = Field(primary_key=True) # e.g., "007"
    name: str # e.g., "Attijariwafa Bank"

class EmployeeRib(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    file_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    rib: Optional[str] = None
    ai_bank_name: Optional[str] = None 
    raw_text: Optional[str] = Field(default=None, sa_column_kwargs={"nullable": True})
    status: str = Field(default="PENDING")
    is_manually_corrected: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)
    period_id: str = Field(foreign_key="period.id")
    period: Period = Relationship(back_populates="ribs")

class EmployeeCIN(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    file_name: str
    cin_number: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[str] = None
    validity_date: Optional[str] = None
    address: Optional[str] = None
    raw_text: Optional[str] = Field(default=None, sa_column_kwargs={"nullable": True})
    status: str = Field(default="PENDING")
    is_manually_corrected: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)
    period_id: str = Field(foreign_key="period.id")
    period: Period = Relationship(back_populates="cins")

class User(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    role: str