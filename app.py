import datetime as dt
import bcrypt
import sys

from feedback.models import FeedbackThread, Comment, Assignment, User
from feedback.db import init_db, SessionLocal

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

def feedback_new(assignment_id, student_id, teacher_id, status, body):
    db = SessionLocal()
    try:
        feedback = FeedbackThread(assignment_id=assignment_id, student_id=student_id, teacher_id=teacher_id, status=status, body=body)
        db.add(feedback)
        db.flush()

        message = Comment(thread_id=feedback.id, author_user_id=teacher_id, body=body, created_at=dt.datetime.now(dt.timezone.utc))
        db.add(message)
        feedback.status = "CLOSED"
        db.commit()
        print(f"Feedback thread {feedback.id} created and closed.")
    finally:
        db.close()

def create_assignment(module_id, title, description, due_date):
    db = SessionLocal()
    try:
        assignment = Assignment(module_id=module_id, title=title, description=description, due_date=due_date)
        db.add(assignment)
        db.commit()
        print(f"Assignment {title} created successfully.")
    finally:
        db.close()

def main():
    print("Python App")
    init_db()
    print("Database initialized.")

    register_user("M123456", "Alice", "staff", "password123")
    login("M123456", "password123")

    # create_assignment("101", "Assignment 1", "For this assignment you must do X, Y and Z", dt.datetime(2025, 12, 31, tzinfo=dt.timezone.utc))
    # feedback_new(1, 1, 1, "OPEN", "Message 1: From teacher to student")
    # feedback_new(1, 1, 1, "OPEN", "Message 2: From student to teacher")

if __name__ == "__main__":
    main()
