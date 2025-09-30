import os
from datetime import datetime
from typing import Optional

from sqlalchemy import (
	create_engine, ForeignKey, String, Integer, DateTime, Text
)
from sqlalchemy.orm import (
	DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, scoped_session
)


class Base(DeclarativeBase):
	pass


class Worker(Base):
	__tablename__ = 'workers'

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	health_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
	full_name: Mapped[str] = mapped_column(String(120))
	age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
	gender: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
	phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
	address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
	native_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
	blood_group: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
	marital_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
	language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
	financial_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
	allergies: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
	conditions: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
	inherited_diseases: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
	previous_treatments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
	vaccination_count: Mapped[int] = mapped_column(Integer, default=0)
	registration_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	face_filename: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	qr_filename: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

	appointments: Mapped[list['Appointment']] = relationship(back_populates='worker', cascade='all, delete-orphan')
	feedbacks: Mapped[list['Feedback']] = relationship(back_populates='worker', cascade='all, delete-orphan')


class Doctor(Base):
	__tablename__ = 'doctors'

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
	full_name: Mapped[str] = mapped_column(String(120))
	speciality: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
	phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

	appointments: Mapped[list['Appointment']] = relationship(back_populates='doctor', cascade='all, delete-orphan')


class Appointment(Base):
	__tablename__ = 'appointments'

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	worker_id: Mapped[int] = mapped_column(ForeignKey('workers.id', ondelete='CASCADE'))
	doctor_id: Mapped[int] = mapped_column(ForeignKey('doctors.id', ondelete='SET NULL'), nullable=True)
	doctor_speciality: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
	status: Mapped[str] = mapped_column(String(24), default='pending')  # pending | confirmed | completed | cancelled
	requested_time: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	worker: Mapped[Worker] = relationship(back_populates='appointments')
	doctor: Mapped[Optional[Doctor]] = relationship(back_populates='appointments')


class Feedback(Base):
	__tablename__ = 'feedback'

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	worker_id: Mapped[int] = mapped_column(ForeignKey('workers.id', ondelete='CASCADE'))
	doctor_id: Mapped[Optional[int]] = mapped_column(ForeignKey('doctors.id', ondelete='SET NULL'), nullable=True)
	rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1..5
	message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	worker: Mapped[Worker] = relationship(back_populates='feedbacks')
	doctor: Mapped[Optional[Doctor]] = relationship()


def get_engine_from_env():
	user = os.getenv('MYSQL_USER', 'root')
	password = os.getenv('MYSQL_PASSWORD', '')
	host = os.getenv('MYSQL_HOST', '127.0.0.1')
	port = os.getenv('MYSQL_PORT', '3306')
	db = os.getenv('MYSQL_DB', 'apna_swastha')
	url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset=utf8mb4"
	return create_engine(url, echo=False, pool_pre_ping=True)


def create_session_factory(engine):
	return scoped_session(sessionmaker(bind=engine, expire_on_commit=False))


def seed_demo_data(Session):
	session = Session()
	try:
		if session.query(Worker).count() > 0:
			return
		# Doctors
		docs = []
		for i, (code, name, spec) in enumerate([
			('D001', 'Dr. Sharma', 'Cardiology'),
			('D002', 'Dr. Patel', 'Pulmonology'),
			('D003', 'Dr. Singh', 'General'),
			('D004', 'Dr. Rao', 'Endocrinology'),
			('D005', 'Dr. Iyer', 'Orthopedics'),
			('D006', 'Dr. Khan', 'Dermatology'),
			('D007', 'Dr. Das', 'Neurology'),
			('D008', 'Dr. Nair', 'ENT'),
			('D009', 'Dr. Banerjee', 'Pediatrics'),
			('D010', 'Dr. Verma', 'Gastroenterology'),
		]):
			d = Doctor(code=code, full_name=name, speciality=spec, phone=f"90000000{i:02d}")
			docs.append(d)
		session.add_all(docs)
		session.flush()

		# Workers
		workers = []
		for i in range(1, 11):
			health_id = f"W10{i:02d}"
			w = Worker(
				health_id=health_id,
				full_name=f"Demo Worker {i}",
				age=20 + i,
				gender='Male' if i % 2 else 'Female',
				phone=f"98{i:08d}",
				address=f"#{i} Demo Street, City",
				native_state='State',
				blood_group='O+' if i % 3 == 0 else 'B+',
				marital_status='Single' if i % 2 else 'Married',
				language='en',
				financial_status='BPL' if i % 3 == 0 else 'APL',
				allergies='Dust' if i % 4 == 0 else '',
				conditions='Hypertension' if i % 5 == 0 else '',
				inherited_diseases='Diabetes' if i % 6 == 0 else '',
				previous_treatments='Vitamin supplements',
				vaccination_count=i % 4,
			)
			workers.append(w)
		session.add_all(workers)
		session.flush()

		# Appointments
		appts = []
		for i, w in enumerate(workers, start=1):
			appts.append(Appointment(worker_id=w.id, doctor_id=docs[i % len(docs)].id, doctor_speciality=docs[i % len(docs)].speciality, status='pending', requested_time='2025-10-01 10:00'))
		session.add_all(appts)

		# Feedback
		feeds = []
		for i, w in enumerate(workers, start=1):
			feeds.append(Feedback(worker_id=w.id, doctor_id=docs[i % len(docs)].id, rating=(i % 5) + 1, message='Demo feedback'))
		session.add_all(feeds)

		session.commit()
	except Exception:
		session.rollback()
		raise
	finally:
		session.close()


