# app/crud.py
from typing import List, Optional, Dict
from sqlmodel import Session, select, col
from app.models import Period, EmployeeRib, EmployeeCIN, User, Bank # Added Bank
import bcrypt

# --- USER FUNCTIONS (Unchanged) ---
def get_user_by_username(db: Session, username: str) -> Optional[User]:
    statement = select(User).where(User.username == username)
    return db.exec(statement).first()

def get_all_users(db: Session) -> List[User]:
    return db.exec(select(User)).all()

def create_user(db: Session, username: str, password: str, role: str) -> User:
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
    if db.exec(select(User)).first():
        return
    print("⚡ Seeding initial users...")
    users_to_create = [
        {"username": "admin", "password": "admin", "role": "admin"},
        {"username": "operator", "password": "operator", "role": "operator"},
        {"username": "superadmin", "password": "superadmin", "role": "superadmin"}
    ]
    for data in users_to_create:
        hashed = bcrypt.hashpw(data["password"].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user = User(username=data["username"], hashed_password=hashed, role=data["role"])
        db.add(user)
    db.commit()
    print("✅ Initial users created")

# --- NEW: BANK FUNCTIONS ---

def get_all_banks(db: Session) -> List[Bank]:
    return db.exec(select(Bank).order_by(Bank.name)).all()

def get_banks_as_dict(db: Session) -> Dict[str, dict]:
    """Returns format expected by validation logic: {'007': {'name': '...'}, ...}"""
    banks = db.exec(select(Bank)).all()
    return {b.code: {'name': b.name} for b in banks}

def create_bank(db: Session, code: str, name: str):
    bank = Bank(code=code, name=name)
    db.add(bank)
    db.commit()
    return bank

def delete_bank(db: Session, code: str):
    bank = db.get(Bank, code)
    if bank:
        db.delete(bank)
        db.commit()

def create_initial_banks(db: Session):
    if db.exec(select(Bank)).first():
        return

    print("⚡ Seeding initial banks...")
    initial_banks = [
        ('007', 'Attijariwafa Bank'),
        ('011', 'BMCE Bank of Africa'),
        ('013', 'BMCI (BNP Paribas)'),
        ('021', 'Crédit du Maroc'),
        ('022', 'Société Générale Maroc'),
        ('031', 'Crédit Agricole du Maroc'),
        ('028', 'Citibank Maghreb'),
        ('101', 'Banque Populaire (Régional)'),
        ('127', 'Banque Populaire'),
        ('145', 'Banque Populaire'),
        ('157', 'Banque Populaire (BCP)'),
        ('190', 'Banque Populaire'),
        ('225', 'Al Barid Bank'),
        ('230', 'CIH Bank'),
        ('310', 'Trésorerie Générale'),
        ('002', 'Bank Al-Maghrib'),
        ('005', 'Arab Bank'),
    ]
    
    for code, name in initial_banks:
        db.add(Bank(code=code, name=name))
    
    db.commit()
    print("✅ Initial banks created")


# --- PERIOD & RIB FUNCTIONS (Unchanged) ---
def get_periods(db: Session) -> List[Period]:
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
    if not rib: return False
    statement = select(EmployeeRib).where(EmployeeRib.period_id == period_id, EmployeeRib.rib == rib)
    return db.exec(statement).first() is not None

def create_rib_entry(db: Session, data: dict) -> EmployeeRib:
    rib_entry = EmployeeRib(**data)
    db.add(rib_entry)
    db.commit()
    db.refresh(rib_entry)
    return rib_entry

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

def delete_all_cins_in_period(db: Session, period_id: str):
    statement = select(EmployeeCIN).where(EmployeeCIN.period_id == period_id)
    results = db.exec(statement).all()
    for cin in results:
        db.delete(cin)
    db.commit()
    return results

def delete_period(db: Session, period_id: str):
    delete_all_ribs_in_period(db, period_id)
    delete_all_cins_in_period(db, period_id)
    period = db.get(Period, period_id)
    if period:
        db.delete(period)
        db.commit()
        return period
    return None

def delete_all_periods(db: Session):
    periods = db.exec(select(Period)).all()
    for period in periods:
        delete_all_ribs_in_period(db, period.id)
        delete_all_cins_in_period(db, period.id)
        db.delete(period)
    db.commit()
    return True   