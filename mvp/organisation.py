"""Organisation catalogue, annual staff allocations and read-only oversight policies."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, String, Text, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .base import Base


class Faculty(Base):
    __tablename__ = "mvp_faculties"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))


class Department(Base):
    __tablename__ = "mvp_departments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    faculty_id: Mapped[str] = mapped_column(ForeignKey("mvp_faculties.id"))
    title: Mapped[str] = mapped_column(String(120))


class CourseDepartment(Base):
    __tablename__ = "mvp_course_departments"
    course_id: Mapped[str] = mapped_column(ForeignKey("mvp_courses.id"), primary_key=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("mvp_departments.id"), primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(20), primary_key=True)


class DepartmentResponsibility(Base):
    __tablename__ = "mvp_department_responsibilities"
    staff_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"), primary_key=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("mvp_departments.id"), primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(20), primary_key=True)
    responsibility: Mapped[str] = mapped_column(String(24), primary_key=True)


class CourseCoordinator(Base):
    __tablename__ = "mvp_course_coordinators"
    course_id: Mapped[str] = mapped_column(ForeignKey("mvp_courses.id"), primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(20), primary_key=True)
    staff_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"), index=True)


class OrganisationChange(Base):
    __tablename__ = "mvp_organisation_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    action: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str] = mapped_column(String(80))
    academic_year: Mapped[str | None] = mapped_column(String(20))
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


DEPARTMENT_ROLES = ("lecturer", "programme_lead", "curriculum_team_lead")


def valid_year(value: str) -> str:
    if not re.fullmatch(r"20\d\d/\d\d", value) or (int(value[:4]) + 1) % 100 != int(value[-2:]):
        raise HTTPException(422, "Use an academic year such as 2026/27.")
    return value


def can_manage_organisation(person, demo_mode: bool) -> bool:
    allowed = {part.strip() for part in os.getenv("FEEDBACK_LOOP_ORGANISATION_ADMIN_USERS", "").split(",") if part.strip()}
    return person.role == "admin" and (person.id in allowed or (demo_mode and person.id == "admin-1"))


class OversightScope:
    """Read access only. Teaching enrolment and feedback ownership still govern writes."""

    def cohort_ids(self, db: Session, person, Cohort) -> set[str]:
        if person.role == "admin":
            return set(db.scalars(select(Cohort.id)).all())
        if person.role != "tutor":
            return set()
        departmental = select(Cohort.id).join(
            CourseDepartment, (CourseDepartment.course_id == Cohort.course_id)
            & (CourseDepartment.academic_year == Cohort.academic_year)
        ).join(
            DepartmentResponsibility, (DepartmentResponsibility.department_id == CourseDepartment.department_id)
            & (DepartmentResponsibility.academic_year == Cohort.academic_year)
        ).where(DepartmentResponsibility.staff_id == person.id,
                DepartmentResponsibility.responsibility.in_(DEPARTMENT_ROLES))
        coordinated = select(Cohort.id).join(
            CourseCoordinator, (CourseCoordinator.course_id == Cohort.course_id)
            & (CourseCoordinator.academic_year == Cohort.academic_year)
        ).where(CourseCoordinator.staff_id == person.id)
        return set(db.scalars(departmental).all()) | set(db.scalars(coordinated).all())

    def enabled(self, db: Session, person) -> bool:
        if person.role == "admin":
            return True
        if person.role != "tutor":
            return False
        return bool(db.scalar(select(DepartmentResponsibility.staff_id).where(
            DepartmentResponsibility.staff_id == person.id,
            DepartmentResponsibility.responsibility.in_(DEPARTMENT_ROLES)).limit(1))
            or db.scalar(select(CourseCoordinator.staff_id).where(
                CourseCoordinator.staff_id == person.id).limit(1)))


class CatalogueItem(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if not value.strip():
            raise ValueError("Title is required.")
        return value.strip()


class DepartmentItem(CatalogueItem):
    faculty_id: str


class CourseDepartments(BaseModel):
    department_ids: list[str] = Field(min_length=1, max_length=100)


class StaffAllocations(BaseModel):
    lecturer_department_ids: list[str] = Field(default_factory=list, max_length=100)
    programme_lead_department_ids: list[str] = Field(default_factory=list, max_length=100)
    curriculum_team_lead_department_ids: list[str] = Field(default_factory=list, max_length=100)
    iv_course_ids: list[str] = Field(default_factory=list, max_length=100)


def staff_allocations(db, staff_id, year):
    data = {role + "_department_ids": [] for role in DEPARTMENT_ROLES}
    for entry in db.scalars(select(DepartmentResponsibility).where(
        DepartmentResponsibility.staff_id == staff_id,
        DepartmentResponsibility.academic_year == year)).all():
        if entry.responsibility in DEPARTMENT_ROLES:
            data[entry.responsibility + "_department_ids"].append(entry.department_id)
    data["iv_course_ids"] = list(db.scalars(select(CourseCoordinator.course_id).where(
        CourseCoordinator.staff_id == staff_id, CourseCoordinator.academic_year == year)).all())
    return {key: sorted(values) for key, values in data.items()}


def audit(db, actor_id, action, subject, year, before, after):
    db.add(OrganisationChange(actor_id=actor_id, action=action, subject=subject, academic_year=year,
                              before_json=json.dumps(before, sort_keys=True), after_json=json.dumps(after, sort_keys=True)))


def commit_configuration(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Configuration changed or already exists. Refresh and try again.") from exc


def register_organisation_routes(app, database, actor, User, Course, demo_mode):
    def require_manager(person=Depends(actor)):
        if not can_manage_organisation(person, demo_mode):
            raise HTTPException(403, "Organisation configuration permission required.")
        return person

    @app.get("/api/organisation")
    def catalogue(academic_year: str, person=Depends(require_manager), db: Session = Depends(database)):
        year = valid_year(academic_year)
        return {
            "academic_year": year,
            "faculties": [{"id": f.id, "title": f.title} for f in db.scalars(select(Faculty).order_by(Faculty.title))],
            "departments": [{"id": d.id, "title": d.title, "faculty_id": d.faculty_id}
                            for d in db.scalars(select(Department).order_by(Department.title))],
            "courses": [{"id": c.id, "title": c.title,
                         "department_ids": sorted(db.scalars(select(CourseDepartment.department_id).where(
                             CourseDepartment.course_id == c.id, CourseDepartment.academic_year == year)).all()),
                         "coordinator_id": coordinator.staff_id if (coordinator := db.get(CourseCoordinator, (c.id, year))) else None}
                        for c in db.scalars(select(Course).order_by(Course.title))],
            "staff": [{"id": u.id, "name": u.name, **staff_allocations(db, u.id, year)}
                      for u in db.scalars(select(User).where(User.role == "tutor").order_by(User.name))],
        }

    @app.post("/api/organisation/faculties", status_code=201)
    def create_faculty(payload: CatalogueItem, person=Depends(require_manager), db: Session = Depends(database)):
        db.add(Faculty(**payload.model_dump()))
        audit(db, person.id, "faculty_created", payload.id, None, {}, payload.model_dump())
        commit_configuration(db)
        return payload.model_dump()

    @app.post("/api/organisation/departments", status_code=201)
    def create_department(payload: DepartmentItem, person=Depends(require_manager), db: Session = Depends(database)):
        if not db.get(Faculty, payload.faculty_id):
            raise HTTPException(422, "Choose an existing faculty.")
        db.add(Department(**payload.model_dump()))
        audit(db, person.id, "department_created", payload.id, None, {}, payload.model_dump())
        commit_configuration(db)
        return payload.model_dump()

    @app.post("/api/organisation/courses", status_code=201)
    def create_course(payload: CatalogueItem, person=Depends(require_manager), db: Session = Depends(database)):
        db.add(Course(**payload.model_dump()))
        audit(db, person.id, "course_created", payload.id, None, {}, payload.model_dump())
        commit_configuration(db)
        return payload.model_dump()

    @app.put("/api/organisation/courses/{course_id}/departments/{academic_year:path}")
    def configure_course(course_id: str, academic_year: str, payload: CourseDepartments,
                         person=Depends(require_manager), db: Session = Depends(database)):
        year = valid_year(academic_year)
        if not db.get(Course, course_id):
            raise HTTPException(404, "Course not found.")
        ids = sorted(set(payload.department_ids))
        if any(not db.get(Department, key) for key in ids):
            raise HTTPException(422, "Choose existing departments.")
        previous = sorted(db.scalars(select(CourseDepartment.department_id).where(
            CourseDepartment.course_id == course_id, CourseDepartment.academic_year == year)).all())
        db.execute(delete(CourseDepartment).where(CourseDepartment.course_id == course_id,
                                                  CourseDepartment.academic_year == year))
        db.add_all(CourseDepartment(course_id=course_id, department_id=key, academic_year=year) for key in ids)
        audit(db, person.id, "course_departments_changed", course_id, year, previous, ids)
        commit_configuration(db)
        return {"course_id": course_id, "academic_year": year, "department_ids": ids}

    @app.put("/api/organisation/staff/{staff_id}/allocations/{academic_year:path}")
    def configure_staff(staff_id: str, academic_year: str, payload: StaffAllocations,
                        person=Depends(require_manager), db: Session = Depends(database)):
        year = valid_year(academic_year)
        staff = db.get(User, staff_id)
        if not staff or staff.role != "tutor":
            raise HTTPException(404, "Approved lecturer account not found.")
        values = {key: sorted(set(ids)) for key, ids in payload.model_dump().items()}
        for role in DEPARTMENT_ROLES:
            if any(not db.get(Department, key) for key in values[role + "_department_ids"]):
                raise HTTPException(422, "Choose existing departments.")
        for key in values["iv_course_ids"]:
            if not db.get(Course, key):
                raise HTTPException(422, "Choose existing courses.")
            coordinator = db.get(CourseCoordinator, (key, year))
            if coordinator and coordinator.staff_id != staff_id:
                raise HTTPException(409, "Course already has an IV Coordinator for this academic year.")
        previous = staff_allocations(db, staff_id, year)
        db.execute(delete(DepartmentResponsibility).where(
            DepartmentResponsibility.staff_id == staff_id, DepartmentResponsibility.academic_year == year))
        db.execute(delete(CourseCoordinator).where(
            CourseCoordinator.staff_id == staff_id, CourseCoordinator.academic_year == year))
        db.add_all(DepartmentResponsibility(staff_id=staff_id, department_id=key, academic_year=year, responsibility=role)
                   for role in DEPARTMENT_ROLES for key in values[role + "_department_ids"])
        db.add_all(CourseCoordinator(course_id=key, academic_year=year, staff_id=staff_id) for key in values["iv_course_ids"])
        audit(db, person.id, "staff_allocations_changed", staff_id, year, previous, values)
        commit_configuration(db)
        return {"staff_id": staff_id, "academic_year": year, **values}
