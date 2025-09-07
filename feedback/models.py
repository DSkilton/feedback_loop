from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from .db import Base
from . import models

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    m_number = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)

class Module(Base):
    __tablename__ = "modules"

    id = Column(Integer, primary_key=True)
    mod_number = Column(String, unique=True)
    title = Column(String)
    spec = Column(String)

class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey("modules.id"))
    title = Column(String)
    description = Column(String)
    due_date = Column(DateTime)

class FeedbackThread(Base):
    __tablename__ = "feedback_threads"

    id = Column(Integer, primary_key=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"))
    student_id = Column(Integer, ForeignKey("users.id"))
    teacher_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String, default="open")
    body = Column(String)

class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    thread_id = Column(Integer, ForeignKey("feedback_threads.id"))
    author_user_id = Column(Integer, ForeignKey("users.id"))
    body = Column(String)
    created_at = Column(DateTime)
