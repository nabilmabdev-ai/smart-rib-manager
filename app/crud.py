# app/crud.py
from typing import List, Optional
from sqlmodel import Session, select, col
from app.models import Period, EmployeeRib, EmployeeCIN, User
import bcrypt # Import bcrypt

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    statement = select(User).where(User.username == username)
    return db.exec(statement).first()

def get_all_users(db: Session) -> List[User]:
    return db.exec(select(User)).all()

def create_user(db: Session, username: str, password: str, role: str) -> User:
    # Hash password
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user = User(username=username, hashed_password=hashed, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def delete_user(db: Session, user_id: int):
    user = db.get(User, user_id)
    if user:
        db.delete(user)
        db.commit()

def update_password(db: Session, user: User, new_password: str):
    hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user.hashed_password = hashed
    db.add(user)
    db.commit()
    db.refresh(user)

def create_initial_users(db: Session):
    # Check if any user exists
    if db.exec(select(User)).first():
        return

    print("⚡ Seeding initial users...")
    
    # Define users with CLEAR TEXT passwords
    users_to_create = [
        {"username": "admin", "password": "admin", "role": "admin"},
        {"username": "operator", "password": "operator", "role": "operator"},
        {"username": "superadmin", "password": "superadmin", "role": "superadmin"}
    ]
    
    for data in users_to_create:
        # dynamic hashing
        hashed = bcrypt.hashpw(data["password"].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        user = User(
            username=data["username"],
            hashed_password=hashed,
            role=data["role"]
        )
        db.add(user)
    
    db.commit()
    print("✅ Initial users created: admin/admin, operator/operator, superadmin/superadmin")

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

def delete_all_cins_in_period(db: Session, period_id: str): # <--- NEW FUNCTION
    statement = select(EmployeeCIN).where(EmployeeCIN.period_id == period_id)
    results = db.exec(statement).all()
    for cin in results:
        db.delete(cin)
    db.commit()
    return results

def delete_period(db: Session, period_id: str):
    # First, delete all associated RIBs and CINs
    delete_all_ribs_in_period(db, period_id)
    delete_all_cins_in_period(db, period_id) # <--- Call new function
    
    # Then, delete the period itself
    period = db.get(Period, period_id)
    if period:
        db.delete(period)
        db.commit()
        return period
    return None

def delete_all_periods(db: Session): # <--- NEW FUNCTION
    periods = db.exec(select(Period)).all()
    for period in periods:
        # Delete associated RIBs and CINs first
        delete_all_ribs_in_period(db, period.id)
        delete_all_cins_in_period(db, period.id)
        # Then delete the period
        db.delete(period)
    db.commit()
    return True