from sqlalchemy import Column, Integer, String
from .db import Base
from . import models

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    m_number = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)

