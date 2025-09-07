import bcrypt
import sys
from feedback.db import init_db, SessionLocal
from feedback.models import User

def register_user(m_number, name, role, password):
    db = SessionLocal()
    try:
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        user = User(m_number=m_number, name=name, role=role, password_hash=pw_hash)
        db.add(user)
        db.commit()
        print(f"User {name} registered successfully.")
    finally:
        db.close()

def login(m_number, password):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(m_number=m_number).first()
        if not user:
            print(f"mNumber {m_number} not found.")
            return
        if bcrypt.checkpw(password.encode(), user.password_hash):
            print(f"Login Successful. Welcome {user.name} ({user.role})")
        else:
            print("Incorrect password.")
    finally:
        db.close()

def main():
    print("Python App")
    init_db()
    print("Database initialized.")

    register_user("M123456", "Alice", "staff", "password123")

    login("M123456", "password123")


if __name__ == "__main__":
    main()
