"""Validated, preview-first CSV and Excel class roster imports."""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, File, Form, HTTPException, UploadFile
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .organisation import audit, can_manage_organisation, valid_year

COLUMNS = ("course_id", "cohort_id", "cohort_name", "academic_year", "user_id", "name", "member_role")
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_EXPANDED_BYTES = 24 * 1024 * 1024
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


@dataclass(frozen=True)
class RosterRow:
    row: int
    course_id: str
    cohort_id: str
    cohort_name: str
    academic_year: str
    user_id: str
    name: str
    member_role: str


@dataclass
class RosterPlan:
    rows: list[RosterRow] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    users: dict = field(default_factory=dict)
    cohorts: dict = field(default_factory=dict)
    memberships: list = field(default_factory=list)
    unchanged: int = 0

    def error(self, number, message):
        self.errors.append({"row": number, "message": message})

    def response(self, digest):
        return {"valid": not self.errors, "sha256": digest, "row_count": len(self.rows),
                "new_learners": len(self.users), "new_cohorts": len(self.cohorts),
                "new_memberships": len(self.memberships), "unchanged": self.unchanged,
                "errors": self.errors[:100], "error_count": len(self.errors),
                "preview": [vars(row) for row in self.rows[:50]],
                "preview_truncated": len(self.rows) > 50}


def excel_values(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 200 or sum(info.file_size for info in entries) > MAX_EXPANDED_BYTES:
            raise ValueError("Workbook expands beyond the permitted size.")
        if any(info.flag_bits & 1 for info in entries):
            raise ValueError("Encrypted workbooks are not supported.")
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    try:
        if len(workbook.worksheets) != 1:
            raise ValueError("Use one worksheet with the roster headers.")
        sheet = workbook.worksheets[0]
        if (sheet.max_row or 0) > MAX_ROWS + 1 or (sheet.max_column or 0) > len(COLUMNS):
            raise ValueError("Workbook exceeds the row or column limit.")
        # Reset untrusted worksheet dimension hints so no data row is silently ignored.
        sheet.reset_dimensions()
        for index, row in enumerate(sheet.iter_rows(), 1):
            if index > MAX_ROWS + 1:
                raise ValueError("Roster exceeds the row limit.")
            if len(row) > len(COLUMNS) and any(cell.value is not None for cell in row[len(COLUMNS):]):
                raise ValueError("Unexpected additional workbook columns.")
            if any(cell.data_type == "f" for cell in row):
                raise ValueError(f"Row {index}: formulas are not permitted.")
            yield [cell.value for cell in row[:len(COLUMNS)]]
    finally:
        workbook.close()


def parse_roster(data, filename):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Upload a non-empty CSV or XLSX file of at most 2 MiB.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        values = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    elif suffix == ".xlsx":
        values = excel_values(data)
    else:
        raise ValueError("Only CSV and XLSX files are supported.")
    plan = RosterPlan()
    headers = next(values, None)
    if headers is None or tuple(headers) != COLUMNS:
        raise ValueError("Use the roster template headers in their specified order.")
    for number, raw in enumerate(values, 2):
        if number > MAX_ROWS + 1:
            raise ValueError("Roster exceeds the row limit.")
        if not any(value is not None and str(value).strip() for value in raw):
            continue
        if len(raw) != len(COLUMNS) or not all(isinstance(value, str) for value in raw):
            plan.error(number, "All seven fields must be text. Format Excel IDs as Text before entering them.")
            continue
        row = RosterRow(number, *(value.strip() for value in raw))
        if not all(ID_PATTERN.fullmatch(value) for value in (row.course_id, row.cohort_id, row.user_id)):
            plan.error(number, "Course, class and account IDs must be non-empty, <=40 characters and use letters, digits, underscores or hyphens.")
            continue
        if not row.cohort_name or len(row.cohort_name) > 120 or not row.name or len(row.name) > 100:
            plan.error(number, "Class and staff/learner names are required and must fit the supported lengths.")
            continue
        try:
            valid_year(row.academic_year)
        except HTTPException:
            plan.error(number, "Use an academic year such as 2026/27.")
            continue
        if row.member_role not in ("learner", "tutor"):
            plan.error(number, "Member role must be learner or tutor.")
            continue
        plan.rows.append(row)
    if not plan.rows:
        plan.error(1, "No valid membership rows were supplied.")
    return plan


def prepare_import(db, plan, User, Course, Cohort, Enrollment):
    seen = set()
    existing_users = {}
    existing_courses = {}
    existing_cohorts = {}
    existing_memberships = {}
    for row in plan.rows:
        key = (row.cohort_id, row.user_id)
        if key in seen:
            plan.error(row.row, "Duplicate account/class membership in this file.")
            continue
        seen.add(key)
        if row.course_id not in existing_courses:
            existing_courses[row.course_id] = db.get(Course, row.course_id)
        if not existing_courses[row.course_id]:
            plan.error(row.row, "Course does not exist; create it in Organisation first.")
            continue
        cohort_spec = (row.course_id, row.cohort_name, row.academic_year)
        if row.cohort_id not in existing_cohorts:
            existing_cohorts[row.cohort_id] = db.get(Cohort, row.cohort_id)
            existing_memberships[row.cohort_id] = {e.user_id: e.member_role for e in db.scalars(
                select(Enrollment).where(Enrollment.cohort_id == row.cohort_id))}
        cohort = existing_cohorts[row.cohort_id]
        if cohort and (cohort.course_id, cohort.name, cohort.academic_year) != cohort_spec:
            plan.error(row.row, "Class ID conflicts with an existing course, class name or academic year.")
            continue
        if not cohort and row.cohort_id in plan.cohorts and plan.cohorts[row.cohort_id] != cohort_spec:
            plan.error(row.row, "The same class ID has inconsistent course, name or academic year in this file.")
            continue
        if row.user_id not in existing_users:
            existing_users[row.user_id] = db.get(User, row.user_id)
        user = existing_users[row.user_id]
        account_spec = (row.name, row.member_role)
        if user and (user.name, user.role) != account_spec:
            plan.error(row.row, "Account ID conflicts with an existing name or role; resolve through approved provisioning.")
            continue
        if not user and row.member_role == "tutor":
            plan.error(row.row, "Lecturer must already have an approved tutor account.")
            continue
        if not user and row.user_id in plan.users and plan.users[row.user_id] != account_spec:
            plan.error(row.row, "The same account ID has inconsistent details in this file.")
            continue
        membership = existing_memberships[row.cohort_id].get(row.user_id)
        if membership and membership != row.member_role:
            plan.error(row.row, "Existing class membership has a different role.")
            continue
        if not cohort:
            plan.cohorts[row.cohort_id] = cohort_spec
        if not user:
            plan.users[row.user_id] = account_spec
        if membership:
            plan.unchanged += 1
        else:
            plan.memberships.append((row.cohort_id, row.user_id, row.member_role))
    return plan


def apply_import(db, plan, User, Cohort, Enrollment):
    if plan.errors:
        raise ValueError("Cannot import an invalid roster.")
    db.add_all(User(id=key, name=name, role=role) for key, (name, role) in plan.users.items())
    db.add_all(Cohort(id=key, course_id=course, name=name, academic_year=year)
               for key, (course, name, year) in plan.cohorts.items())
    db.flush()
    db.add_all(Enrollment(cohort_id=cohort, user_id=user, member_role=role)
               for cohort, user, role in plan.memberships)


def register_roster_routes(app, database, actor, User, Course, Cohort, Enrollment, demo_mode):
    @app.post("/api/organisation/rosters")
    async def roster_upload(file: UploadFile = File(...), expected_sha256: str = Form(default=""),
                            person=Depends(actor), db: Session = Depends(database)):
        if not can_manage_organisation(person, demo_mode):
            raise HTTPException(403, "Organisation configuration permission required.")
        data = await file.read(MAX_BYTES + 1)
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 and digest != expected_sha256:
            raise HTTPException(409, "File changed since preview; preview the new file.")
        try:
            plan = parse_roster(data, file.filename or "")
        except (ValueError, UnicodeError, csv.Error, zipfile.BadZipFile, OSError) as exc:
            raise HTTPException(422, "Invalid roster file: " + str(exc)[:250]) from exc
        except Exception as exc:
            # Workbook parsing errors must not leak internal XML or server paths.
            raise HTTPException(422, "Unable to read workbook. Use a valid single-sheet XLSX roster.") from exc
        prepare_import(db, plan, User, Course, Cohort, Enrollment)
        result = plan.response(digest)
        if not expected_sha256:
            return {**result, "imported": False}
        if not plan.errors:
            try:
                apply_import(db, plan, User, Cohort, Enrollment)
                audit(db, person.id, "roster_imported", digest, None, {},
                      {key: result[key] for key in ("sha256", "row_count", "new_learners", "new_cohorts", "new_memberships", "unchanged")})
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(409, "Roster changed during import; preview again.") from exc
            return {**result, "imported": True}
        return {**result, "imported": False}
