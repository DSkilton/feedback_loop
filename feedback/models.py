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
