# app/models.py
from typing import Optional, List
from datetime import datetime
import uuid
from sqlmodel import Field, Relationship, SQLModel

class Period(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.now)
    
    # If True, no more uploads or edits allowed
    is_locked: bool = Field(default=False)
    
    # Relationships
    ribs: List["EmployeeRib"] = Relationship(back_populates="period")
    cins: List["EmployeeCIN"] = Relationship(back_populates="period")

class EmployeeRib(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    file_name: str
    
    # Extracted Data
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    rib: Optional[str] = None
    ai_bank_name: Optional[str] = None 
    
    # Meta Data
    raw_text: Optional[str] = Field(default=None, sa_column_kwargs={"nullable": True})
    status: str = Field(default="PENDING") # PENDING, SUCCESS, ERROR, DUPLICATE, SUSPICIOUS
    is_manually_corrected: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)
    
    # Foreign Key
    period_id: str = Field(foreign_key="period.id")
    period: Period = Relationship(back_populates="ribs")

class EmployeeCIN(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    file_name: str
    
    # Extracted Data (HR "Source of Truth")
    cin_number: Optional[str] = None      # The Key Identifier (e.g., BJ488277)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[str] = None      # Kept as string (DD/MM/YYYY) to avoid parsing errors during OCR
    validity_date: Optional[str] = None   # Crucial for HR alerts (expiry)
    address: Optional[str] = None
    
    # Meta Data
    raw_text: Optional[str] = Field(default=None, sa_column_kwargs={"nullable": True})
    status: str = Field(default="PENDING") # PENDING, VALID, EXPIRED, ERROR, SUSPICIOUS
    is_manually_corrected: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)
    
    # Foreign Key
    period_id: str = Field(foreign_key="period.id")
    period: Period = Relationship(back_populates="cins")

class User(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    role: str # "admin", "operator", "superadmin"