# app/crud.py
from sqlmodel import Session, select, col
from app.models import Period, EmployeeRib
from typing import List, Optional

def get_periods(db: Session) -> List[Period]:
    # Get periods ordered by newest first
    statement = select(Period).order_by(col(Period.created_at).desc())
    return db.exec(statement).all()

def get_period_by_id(db: Session, period_id: str) -> Optional[Period]:
    return db.get(Period, period_id)

def create_period(db: Session, name: str) -> Period:
    period = Period(name=name)
    db.add(period)
    db.commit()
    db.refresh(period)
    return period

def check_duplicate_rib(db: Session, period_id: str, rib: str) -> bool:
    if not rib:
        return False
    statement = select(EmployeeRib).where(
        EmployeeRib.period_id == period_id,
        EmployeeRib.rib == rib
    )
    result = db.exec(statement).first()
    return result is not None

def create_rib_entry(db: Session, data: dict) -> EmployeeRib:
    rib_entry = EmployeeRib(**data)
    db.add(rib_entry)
    db.commit()
    db.refresh(rib_entry)
    return rib_entry

def update_rib_entry(db: Session, rib_id: str, first_name: str, last_name: str, rib: str):
    entry = db.get(EmployeeRib, rib_id)
    if entry:
        entry.first_name = first_name
        entry.last_name = last_name
        entry.rib = rib
        entry.status = "SUCCESS" # Manually verified
        db.add(entry)
        db.commit()
        db.refresh(entry)
    return entry

def delete_rib_entry(db: Session, rib_id: str):
    entry = db.get(EmployeeRib, rib_id)
    if entry:
        db.delete(entry)
        db.commit()
        return entry
    return None

def delete_all_ribs_in_period(db: Session, period_id: str):
    statement = select(EmployeeRib).where(EmployeeRib.period_id == period_id)
    results = db.exec(statement).all()
    for rib in results:
        db.delete(rib)
    db.commit()
    return results

def delete_period(db: Session, period_id: str):
    # First, delete all associated RIBs
    delete_all_ribs_in_period(db, period_id)
    
    # Then, delete the period itself
    period = db.get(Period, period_id)
    if period:
        db.delete(period)
        db.commit()
        return period
    return None