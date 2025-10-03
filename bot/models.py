from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, DateTime, BigInteger
from sqlalchemy.orm import relationship
from datetime import datetime

# Импортируем Base из db.py
from db import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, index=True)  # Изменено на BigInteger
    is_admin = Column(Boolean, default=False)

class Subject(Base):
    __tablename__ = "subjects"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    labs = relationship("Lab", back_populates="subject")

class Lab(Base):
    __tablename__ = "labs"
    
    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"))
    title = Column(String, index=True)
    desc = Column(Text, nullable=True)
    deadline = Column(String, nullable=True)
    
    subject = relationship("Subject", back_populates="labs")
    files = relationship("LabFile", back_populates="lab")

class LabFile(Base):
    __tablename__ = "lab_files"
    
    id = Column(Integer, primary_key=True, index=True)
    lab_id = Column(Integer, ForeignKey("labs.id"))
    file_name = Column(String)
    file_path = Column(String)
    file_size = Column(Integer)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    lab = relationship("Lab", back_populates="files")