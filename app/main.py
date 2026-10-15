"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os

from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, EmailStr, field_validator, model_validator

from pymongo import MongoClient
from pymongo.errors import PyMongoError, DuplicateKeyError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

# --------------------------------------------------------------------------- #
# MongoDB Indexes
# --------------------------------------------------------------------------- #

def create_indexes():
    """
    Create indexes required by the application.
    create_index() is idempotent when the same index
    specification and options are used.
    """

    # Employees collection

    # Every employee must have a unique employee code.
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="uq_employee_emp_code"
    )

    # Helps filter employees by department and sort by employee code.
    db.employees.create_index(
        [("department", 1), ("emp_code", 1)],
        name="idx_employee_department_emp_code"
    )

    # Helps monthly and daily headcount queries.
    db.employees.create_index(
        [("joined_on", 1), ("department", 1)],
        name="idx_employee_joined_department"
    )

    # Attendance collection

    # An employee can have only one attendance record per date.
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="uq_attendance_employee_date"
    )

    # Helps attendance date sorting and date-range filtering.
    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="idx_attendance_date_emp_code"
    )

    # Helps queries filtering attendance by status and date.
    db.attendance_logs.create_index(
        [("status", 1), ("date", -1)],
        name="idx_attendance_status_date"
    )

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def startup_event():
    try:
        create_indexes()
        print("MongoDB indexes created successfully.")
    except PyMongoError as error:
        print(f"MongoDB index creation failed: {error}")
        raise


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def normalize_timestamp(punched_at: Optional[int] = None) -> datetime:
    """
    Convert epoch milliseconds into a UTC datetime.
    If no timestamp is provided, use the current UTC time.
    Truncate microseconds.
    """

    if punched_at is None:
        return datetime.now(timezone.utc).replace(microsecond=0)

    if isinstance(punched_at, bool) or not isinstance(punched_at, int):
        raise ValueError("punched_at must be an integer in epoch milliseconds")

    
    if punched_at < 100000000000 or punched_at > 4102444800000:
        raise ValueError("punched_at is outside the supported range")


    try:
        return datetime.fromtimestamp(
            punched_at / 1000,
            tz=timezone.utc
        ).replace(microsecond=0)

    except (ValueError, OverflowError, OSError):
        raise ValueError("punched_at is outside the supported range")


def to_ist(timestamp: datetime) -> datetime:
    """
    Convert UTC datetime into IST.
    """

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(IST)


def get_attendance_date(punch_in: datetime, employee: dict) -> str:
    """
    Determine attendance date using the employee's shift.

    For an overnight shift, a punch-in before shift_end
    belongs to the previous day's shift.
    """

    local_time = to_ist(punch_in)

    shift_start = employee["shift_start"]
    shift_end = employee["shift_end"]

    is_overnight = shift_end <= shift_start

    attendance_date = local_time.date()

    if is_overnight and local_time.strftime("%H:%M") < shift_end:
        attendance_date -= timedelta(days=1)

    return attendance_date.isoformat()


def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    attendance_date: str,
    shift_end: str
) -> int:

    local_punch_in = to_ist(punch_in)

    is_overnight = shift_end <= shift_start

    # Early-morning punch-in belongs to the previous shift.
    if (
        is_overnight
        and local_punch_in.date() > datetime.fromisoformat(attendance_date).date()
        and local_punch_in.strftime("%H:%M") < shift_end
    ):
        return 0

    shift_hour, shift_minute = map(int, shift_start.split(":"))

    shift_start_dt = datetime.fromisoformat(
        attendance_date
    ).replace(
        hour=shift_hour,
        minute=shift_minute,
        second=0,
        microsecond=0,
        tzinfo=IST
    )

    elapsed_seconds = (
        local_punch_in - shift_start_dt
    ).total_seconds()

    if elapsed_seconds <= 600:
        return 0

    return int(elapsed_seconds // 60)


def compute_work_hours(
    punch_in: datetime,
    punch_out: datetime
) -> float:
    """
    Calculate elapsed working hours.
    Round to 2 decimal places using ROUND_HALF_UP.
    """

    from decimal import Decimal, ROUND_HALF_UP

    seconds = Decimal(
        str((punch_out - punch_in).total_seconds())
    )

    hours = seconds / Decimal("3600")

    return float(
        hours.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    )


def compute_overtime(
    punch_out: datetime,
    shift_end: str,
    attendance_date: str,
    shift_start: str
) -> int:
    """
    Calculate overtime in whole minutes.

    Overtime is counted only when the employee
    works at least 30 minutes beyond shift end.
    """

    local_punch_out = to_ist(punch_out)

    shift_hour, shift_minute = map(int, shift_end.split(":"))

    shift_end_date = datetime.fromisoformat(attendance_date).date()

    # Overnight shifts end on the following calendar day.
    if shift_end <= shift_start:
        shift_end_date += timedelta(days=1)

    shift_end_dt = datetime.combine(
        shift_end_date,
        datetime.min.time(),
        tzinfo=IST
    ).replace(
        hour=shift_hour,
        minute=shift_minute
    )

    elapsed_seconds = (
        local_punch_out - shift_end_dt
    ).total_seconds()

    overtime_minutes = int(elapsed_seconds // 60)

    if overtime_minutes < 30:
        return 0

    return overtime_minutes

def employee_response(doc):
    """
    Convert MongoDB employee document into API response format.
    MongoDB stores created_at as a datetime.
    API returns created_at as epoch milliseconds.
    """

    created_at = doc.get("created_at")

    if created_at is not None:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        doc["created_at"] = int(created_at.timestamp() * 1000)

    doc.pop("_id", None)

    return doc

def ensure_utc_aware(timestamp: datetime) -> datetime:
    """
    Ensure a MongoDB datetime is treated as UTC-aware.
    """

    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(timezone.utc)

def timestamp_to_ms(value):
    """
    Convert a datetime into epoch milliseconds for API responses.
    """

    if value is None:
        return None

    value = ensure_utc_aware(value)

    return int(value.timestamp() * 1000)


def attendance_api_response(doc):
    """
    Convert attendance timestamps, including history timestamps,
    into epoch milliseconds for API responses.
    """

    result = dict(doc)

    result["punch_in"] = timestamp_to_ms(
        result.get("punch_in")
    )

    result["punch_out"] = timestamp_to_ms(
        result.get("punch_out")
    )

    result["late_minutes"] = result.get("late_minutes", 0)
    result["overtime_minutes"] = result.get("overtime_minutes", 0)
    result["half_day"] = result.get("half_day", False)

    result["history"] = result.get("history", [])

    converted_history = []

    for entry in result["history"]:
        item = dict(entry)

        item["at"] = timestamp_to_ms(item["at"])

        converted_changes = {}

        for field, values in item["changes"].items():
            converted_values = dict(values)

            if field in ("punch_in", "punch_out"):
                converted_values["from"] = timestamp_to_ms(
                    converted_values.get("from")
                )
                converted_values["to"] = timestamp_to_ms(
                    converted_values.get("to")
                )

            converted_changes[field] = converted_values

        item["changes"] = converted_changes
        converted_history.append(item)

    result["history"] = converted_history
    result.pop("_id", None)
  

    return result
# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: EmailStr
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("emp_code", "name", "email", "department")
    @classmethod
    def validate_text_fields(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be empty")

        return value

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value):
        try:
            parsed_date = datetime.strptime(value, "%Y-%m-%d")

            if parsed_date.strftime("%Y-%m-%d") != value:
                raise ValueError

        except ValueError:
            raise ValueError("joined_on must be in YYYY-MM-DD format")

        return value

    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_shift_time(cls, value):
        try:
            parsed_time = datetime.strptime(value, "%H:%M")

            if parsed_time.strftime("%H:%M") != value:
                raise ValueError

        except ValueError:
            raise ValueError("Shift time must be in HH:MM format")

        return value

    @model_validator(mode="after")
    def validate_shift(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end cannot be equal")

        return self


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("emp_code")
    @classmethod
    def validate_emp_code(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("emp_code cannot be empty")

        return value

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("punched_at must be an integer in epoch milliseconds")

        
        if value < 100000000000 or value > 4102444800000:
            raise ValueError("punched_at is outside the supported range")


        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        allowed_statuses = ["PRESENT", "WFH", "ON_DUTY"]

        if value not in allowed_statuses:
            raise ValueError(
                "status must be PRESENT, WFH, or ON_DUTY"
            )

        return value

class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

    @field_validator("emp_code")
    @classmethod
    def validate_emp_code(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("emp_code cannot be empty")

        return value

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "punched_at must be an integer in epoch milliseconds"
            )

        
        if value < 100000000000 or value > 4102444800000:
            raise ValueError(
                "punched_at is outside the supported range"
            )


        return value

class AttendanceRegularizationIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None

    reason: str
    regularized_by: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value is None:
            return value

        allowed_statuses = [
            "PRESENT",
            "WFH",
            "ON_DUTY",
            "ABSENT",
            "LEAVE"
        ]

        if value not in allowed_statuses:
            raise ValueError("Invalid attendance status")

        return value

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def validate_timestamps(cls, value):
        if value is None:
            return value

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "Punch timestamps must be integer epoch milliseconds"
            )

        if value < 100000000000 or value > 4102444800000:
            raise ValueError(
                "Punch timestamp is outside the supported range"
            )

        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value):
        value = value.strip()

        if not 5 <= len(value) <= 200:
            raise ValueError(
                "reason must contain between 5 and 200 characters"
            )

        return value

    @field_validator("regularized_by")
    @classmethod
    def validate_regularized_by(cls, value):
        value = value.strip()

        if not 1 <= len(value) <= 50:
            raise ValueError(
                "regularized_by must contain between 1 and 50 characters"
            )

        return value       


def build_attendance_filter(
    emp_code=None,
    date_from=None,
    date_to=None,
    status=None
):
    """
    Build the MongoDB filter for attendance records.

    This helper is shared by the attendance list
    endpoint and the Admin Explain API.
    """

    query = {}

    if emp_code:
        query["emp_code"] = emp_code.strip()

    if date_from or date_to:
        query["date"] = {}

        if date_from:
            query["date"]["$gte"] = date_from

        if date_to:
            query["date"]["$lte"] = date_to

    if status:
        query["status"] = status

    return query
def build_attendance_sort():
    """
    Return the standard sorting order for attendance records.
    """
    return [
        ("date", -1),
        ("emp_code", 1)
    ]   
# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="MongoDB connection failed"
        )


@app.post(
    "/employees", 
    status_code=201,
    responses={
        409: {"description": "Employee code already exists"},
        503: {"description": "Database operation failed"}
    }
)
def create_employee(body: EmployeeIn):

    # Check whether the employee code already exists.
    existing_employee = db.employees.find_one(
        {"emp_code": body.emp_code}
    )

    if existing_employee:
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists"
        )

    # Convert the validated Pydantic model into a dictionary.
    doc = body.model_dump()

    # Store created_at in UTC and truncate microseconds.
    doc["created_at"] = datetime.now(timezone.utc).replace(
        microsecond=0
    )

    try:
        db.employees.insert_one(doc)

    except DuplicateKeyError:
        # Handles two simultaneous requests with the same emp_code.
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists"
        )

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed"
        )

    return employee_response(doc)


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100)
):

    # Build the MongoDB filter.
    query = {}

    if department:
        query["department"] = department

    try:
        # Count employees matching the filter.
        total = db.employees.count_documents(query)

        # Calculate how many documents to skip.
        skip = (page - 1) * page_size

        # Fetch only the requested page.
        cursor = (
            db.employees.find(query, {"_id": 0})
            .sort("emp_code", 1)
            .skip(skip)
            .limit(page_size)
        )

        items = [
            employee_response(doc)
            for doc in cursor
        ]

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed"
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@app.post(
    "/attendance/punch-in",
    status_code=201,
    responses={
        409: {"description": "Employee has already punched in for this date"},
        404: {"description": "Employee not found"},
        422: {"description": "Validation error"}
    }
)
def punch_in(body: PunchInIn):

    # 1. Check whether the employee exists.
    emp = db.employees.find_one(
        {"emp_code": body.emp_code}
    )

    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    # 2. Convert the supplied timestamp into UTC.
    try:
        ts = normalize_timestamp(body.punched_at)

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

    # 3. Determine the correct IST attendance date.
    attendance_date = get_attendance_date(ts, emp)

    # 4. Calculate late minutes.
    late_minutes = compute_late_minutes(
    ts,
    emp["shift_start"],
    attendance_date,
    emp["shift_end"]
    )

    # 5. Prepare the attendance document.
    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": late_minutes,
        "overtime_minutes": 0,
        "half_day": False,
        "history": []
    }

    # 6. Insert the document.
    try:
        db.attendance_logs.insert_one(doc)

    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Already punched in for this date"
        )

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed"
        )

    # 7. Return the attendance record.
    doc["punch_in"] = int(ts.timestamp() * 1000)

    # Remove MongoDB internal ID from the API response.
    doc.pop("_id", None)

    return doc


@app.post(
    "/attendance/punch-out",
    responses={
        404: {"description": "Employee or punch-in record not found"},
        409: {"description": "Attendance already punched out"},
        422: {"description": "Invalid punch-out timestamp or punch-out time"},
        503: {"description": "Database operation failed"}
    }
)
def punch_out(body: PunchOutIn):

    # 1. Check whether the employee exists.
    emp = db.employees.find_one(
        {"emp_code": body.emp_code}
    )

    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    # 2. Convert the supplied timestamp into UTC.
    try:
        ts = normalize_timestamp(body.punched_at)

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

    # 3. Find the most recent open attendance record
    # whose punch-in is not later than punch-out.
    
    attendance = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$lte": ts},
            "punch_out": None
        },
        sort=[("punch_in", -1)]
    )
 

    # 4. If no open record exists, distinguish between
    # an already closed record and no punch-in.

    if attendance is None:
        closed_record = db.attendance_logs.find_one(
            {
                "emp_code": body.emp_code,
                "punch_in": {"$lte": ts},
                "punch_out": {"$ne": None}
            },
            sort=[("punch_in", -1)]
        )

        if closed_record:
            raise HTTPException(
                status_code=409,
                detail="Attendance already punched out"
            )

        raise HTTPException(
            status_code=404,
            detail="No open punch-in record found"
        )




    # 5. Convert MongoDB punch-in into UTC-aware datetime.
    punch_in_time = ensure_utc_aware(
        attendance["punch_in"]
    )

    # 6. Validate punch-out time.
    if ts <= punch_in_time:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be later than punch-in"
        )

    elapsed_seconds = (
        ts - punch_in_time
    ).total_seconds()

    if elapsed_seconds > 24 * 60 * 60:
        raise HTTPException(
            status_code=422,
            detail="Punch-out cannot be more than 24 hours after punch-in"
        )

    # 7. Calculate work hours.
    work_hours = compute_work_hours(
        punch_in_time,
        ts
    )

    # 8. Calculate overtime.
    overtime_minutes = compute_overtime(
        ts,
        emp["shift_end"],
        attendance["date"],
        emp["shift_start"]
    )

    # 9. Calculate half-day.
    half_day = work_hours < 4.50

    # 10. Update the existing attendance record.
    try:
        result = db.attendance_logs.update_one(
            {
                "_id": attendance["_id"],
                "punch_out": None
            },
            {
                "$set": {
                    "punch_out": ts,
                    "work_hours": work_hours,
                    "overtime_minutes": overtime_minutes,
                    "half_day": half_day
                }
            }
        )

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed"
        )

    # Another simultaneous punch-out may have updated it first.
    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Attendance already punched out"
        )

    # 11. Prepare the API response.
    attendance["punch_out"] = int(ts.timestamp() * 1000)
    attendance["punch_in"] = int(
        punch_in_time.timestamp() * 1000
    )
    attendance["work_hours"] = work_hours
    attendance["overtime_minutes"] = overtime_minutes
    attendance["half_day"] = half_day

    attendance.pop("_id", None)

    return attendance

@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: AttendanceRegularizationIn
):

    # 1. Validate the attendance date.
    try:
        parsed_date = datetime.strptime(date, "%Y-%m-%d")

        if parsed_date.strftime("%Y-%m-%d") != date:
            raise ValueError

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="date must be in YYYY-MM-DD format"
        )

    # 2. Find the employee.
    employee = db.employees.find_one(
        {"emp_code": emp_code}
    )

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    # 3. Find the attendance record.
    attendance = db.attendance_logs.find_one(
        {
            "emp_code": emp_code,
            "date": date
        }
    )

    if not attendance:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found"
        )

    # 4. Get the fields explicitly supplied by the client.
    supplied_fields = body.model_fields_set

    # 5. Get the final attendance status.
    old_status = attendance.get("status")
    new_status = (
        body.status
        if "status" in supplied_fields
        else old_status
    )

    # 6. Get the old punch timestamps.
    old_punch_in = attendance.get("punch_in")
    old_punch_out = attendance.get("punch_out")

    if old_punch_in is not None:
        old_punch_in = ensure_utc_aware(old_punch_in)

    if old_punch_out is not None:
        old_punch_out = ensure_utc_aware(old_punch_out)

    # 7. Apply only the punch fields supplied by the client.
    try:
        new_punch_in = (
            normalize_timestamp(body.punch_in)
            if "punch_in" in supplied_fields and body.punch_in is not None
            else None if "punch_in" in supplied_fields
            else old_punch_in
        )

        new_punch_out = (
            normalize_timestamp(body.punch_out)
            if "punch_out" in supplied_fields and body.punch_out is not None
            else None if "punch_out" in supplied_fields
            else old_punch_out
        )

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

    # 8. ABSENT and LEAVE records cannot have punch times.
    if new_status in ["ABSENT", "LEAVE"]:

        if "punch_in" in supplied_fields or "punch_out" in supplied_fields:
            raise HTTPException(
                status_code=422,
                detail="Punch times cannot be supplied for ABSENT or LEAVE"
            )

        new_punch_in = None
        new_punch_out = None

    # 9. PRESENT, WFH and ON_DUTY require punch-in.
    else:

        if new_punch_in is None:
            raise HTTPException(
                status_code=422,
                detail="A punch_in timestamp is required for presence statuses"
            )

        # Punch-in must belong to the attendance date.
        calculated_date = get_attendance_date(
            new_punch_in,
            employee
        )

        if calculated_date != date:
            raise HTTPException(
                status_code=422,
                detail="Punch-in does not belong to this attendance date"
            )

        # Punch-out must be after punch-in.
        if new_punch_out is not None:

            if new_punch_out <= new_punch_in:
                raise HTTPException(
                    status_code=422,
                    detail="Punch-out must be later than punch-in"
                )

            elapsed = (
                new_punch_out - new_punch_in
            ).total_seconds()

            if elapsed > 24 * 60 * 60:
                raise HTTPException(
                    status_code=422,
                    detail="Punch-out cannot be more than 24 hours after punch-in"
                )

    # 10. Recalculate derived fields.
    if new_status in ["ABSENT", "LEAVE"]:

        work_hours = None
        late_minutes = 0
        overtime_minutes = 0
        half_day = False

    else:

        late_minutes = compute_late_minutes(
            new_punch_in,
            employee["shift_start"],
            date,
            employee["shift_end"]
        )

        if new_punch_out is not None:

            work_hours = compute_work_hours(
                new_punch_in,
                new_punch_out
            )

            overtime_minutes = compute_overtime(
                new_punch_out,
                employee["shift_end"],
                date,
                employee["shift_start"]
            )

            half_day = work_hours < 4.50

        else:

            work_hours = None
            overtime_minutes = 0
            half_day = False

    # 11. Prepare old and new values for audit history.
    old_values = {
        "status": old_status,
        "punch_in": old_punch_in,
        "punch_out": old_punch_out,
        "work_hours": attendance.get("work_hours"),
        "late_minutes": attendance.get("late_minutes", 0),
        "overtime_minutes": attendance.get("overtime_minutes", 0),
        "half_day": attendance.get("half_day", False)
    }

    new_values = {
        "status": new_status,
        "punch_in": new_punch_in,
        "punch_out": new_punch_out,
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day
    }

    # 12. Include only fields whose values actually changed.
    changes = {}

    for field in new_values:

        old_value = old_values[field]
        new_value = new_values[field]

        if old_value != new_value:

            changes[field] = {
                "from": old_value,
                "to": new_value
            }

    # 13. Reject requests that make no actual change.
    if not changes:
        raise HTTPException(
            status_code=422,
            detail="No changes detected"
        )

    # 14. Create exactly one history entry.
    history_entry = {
        "at": datetime.now(timezone.utc).replace(microsecond=0),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes
    }

    # 15. Update attendance and append history atomically.
    old_history = attendance.get("history", [])

    update_filter = {
        "_id": attendance["_id"],
        "emp_code": emp_code,
        "date": date,
        "status": old_status,
        "punch_in": attendance.get("punch_in"),
        "punch_out": attendance.get("punch_out"),
        "$or": [
            {"history": old_history},
            {"history": {"$exists": False}}
        ]
    }

    try:

        result = db.attendance_logs.update_one(
            update_filter,
            {
                "$set": new_values,
                "$push": {
                    "history": history_entry
                }
            }
        )

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed"
        )

    # 16. Detect concurrent modifications.
    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Attendance was modified by another request. Please retry."
        )

    # 17. Return the updated attendance record.
    updated = db.attendance_logs.find_one(
        {
            "emp_code": emp_code,
            "date": date
        }
    )

    return attendance_api_response(updated)


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    # 1. Validate date_from
    if date_from:
        try:
            parsed_date = datetime.strptime(date_from, "%Y-%m-%d")
            if parsed_date.strftime("%Y-%m-%d") != date_from:
                raise ValueError
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="date_from must be in YYYY-MM-DD format"
            )

    # 2. Validate date_to
    if date_to:
        try:
            parsed_date = datetime.strptime(date_to, "%Y-%m-%d")
            if parsed_date.strftime("%Y-%m-%d") != date_to:
                raise ValueError
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="date_to must be in YYYY-MM-DD format"
            )

    # 3. Validate date range
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from cannot be greater than date_to"
        )

    # 4. Validate status
    allowed_statuses = [
        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
    ]

    if status and status not in allowed_statuses:
        raise HTTPException(
            status_code=422,
            detail="Invalid attendance status"
        )

        # 5. Build MongoDB filter using shared helper
    q = build_attendance_filter(
        emp_code=emp_code,
        date_from=date_from,
        date_to=date_to,
        status=status
    )

    try:
        # 6. Get total records matching the filters
        total = db.attendance_logs.count_documents(q)

        # 7. Fetch only the required page from MongoDB
        docs = list(
            db.attendance_logs.find(q)
            .sort(build_attendance_sort())
            .skip((page - 1) * page_size)
            .limit(page_size)
        )

        # 8. Convert MongoDB records into API responses
        items = [
            attendance_api_response(doc)
            for doc in docs
        ]

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed"
    )

    # 9. Return paginated response
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }

@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(
    emp_code: str,
    month: str 
):
    from decimal import Decimal, ROUND_HALF_UP

    # 1. Validate the month
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError

        month_start = datetime.strptime(
            month + "-01", "%Y-%m-%d"
        ).date()

        if month_start.strftime("%Y-%m") != month:
             raise ValueError

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format with a valid month"
        )

    # 2. Calculate the first and last day of the month
    if month_start.month == 12:
        next_month = datetime(
            month_start.year + 1, 1, 1
        ).date()
    else:
        next_month = datetime(
            month_start.year,
            month_start.month + 1,
            1
        ).date()

    month_end = next_month - timedelta(days=1)

    month_start_str = month_start.isoformat()
    month_end_str = month_end.isoformat()

    # 3. Find the employee
    employee = db.employees.find_one(
        {"emp_code": emp_code},
        {"_id": 0, "joined_on": 1}
    )

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    # 4. Calculate working days from joining date
    joined_on = datetime.strptime(
        employee["joined_on"], "%Y-%m-%d"
    ).date()

    current_day = max(joined_on, month_start)
    working_days = 0

    while current_day <= month_end:
        if current_day.weekday() < 5:
            working_days += 1

        current_day += timedelta(days=1)

    # 5. MongoDB aggregation pipeline
    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": month_start_str,
                    "$lte": month_end_str
                }
            }
        },
        {
            "$addFields": {
                "weekday": {
                    "$dayOfWeek": {
                        "$dateFromString": {
                            "dateString": "$date"
                        }
                    }
                }
            }
        },
        {
            "$group": {
                "_id": None,

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {"$gte": ["$weekday", 2]},
                                    {"$lte": ["$weekday", 6]}
                                ]
                            },
                            {
                                "$cond": [
                                    {
                                        "$eq": [
                                            {"$ifNull": ["$half_day", False]},
                                            True
                                        ]
                                    },
                                    0.5,
                                    1.0
                                ]
                            },
                            0
                        ]
                    }
                },

                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },

                
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$gt": [
                                    {"$ifNull": ["$late_minutes", 0]},
                                    0
                                ]
                            },
                            1,
                            0
                        ]
                    }
                },

                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },

                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                }

            }

         
        }
    ]

    # 6. Execute aggregation
    result = list(
        db.attendance_logs.aggregate(pipeline)
    )

    # 7. Handle employees with no attendance records
    
    if result:
        present_days = result[0]["present_days"]
        leave_days = result[0]["leave_days"]
        late_count = result[0]["late_count"]
        total_late_minutes = result[0]["total_late_minutes"]
        total_overtime_minutes = result[0]["total_overtime_minutes"]
    else:
        present_days = 0
        leave_days = 0
        late_count = 0
        total_late_minutes = 0
        total_overtime_minutes = 0


    # 8. Calculate attendance percentage
    if working_days > 0:
        attendance_pct = (
            Decimal(str(present_days))
            / Decimal(str(working_days))
            * Decimal("100")
        ).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP
        )

        attendance_pct = float(attendance_pct)
    else:
        attendance_pct = None

    # 9. Return monthly analytics
    
    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": leave_days,
        "late_count": late_count,
        "attendance_pct": attendance_pct,
        "total_late_minutes": total_late_minutes,
        "total_overtime_minutes": total_overtime_minutes
    }


@app.get("/analytics/departments/summary")
def department_summary(
    month: str,
    department: Optional[str] = None
):
    from decimal import Decimal, ROUND_HALF_UP

    # 1. Validate month format
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError

        month_start = datetime.strptime(
            month + "-01", "%Y-%m-%d"
        ).date()

        if month_start.strftime("%Y-%m") != month:
            raise ValueError

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format with a valid month"
        )

    # 2. Calculate month end
    if month_start.month == 12:
        next_month = datetime(
            month_start.year + 1, 1, 1
        ).date()
    else:
        next_month = datetime(
            month_start.year,
            month_start.month + 1,
            1
        ).date()

    month_end = next_month - timedelta(days=1)
    month_end_str = month_end.isoformat()

    # 3. Build employee filter
    employee_match = {
        "joined_on": {"$lte": month_end_str}
    }

    if department:
        employee_match["department"] = department

    # 4. MongoDB aggregation pipeline
    pipeline = [
        {
            "$match": employee_match
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {
                                        "$eq": [
                                            "$emp_code",
                                            "$$employee_code"
                                        ]
                                    },
                                    {
                                        "$gte": [
                                            "$date",
                                            month_start.isoformat()
                                        ]
                                    },
                                    {
                                        "$lte": [
                                            "$date",
                                            month_end_str
                                        ]
                                    }
                                ]
                            }
                        }
                    }
                ],
                "as": "attendance"
            }
        },
        {
            "$unwind": {
                "path": "$attendance",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$group": {
                "_id": "$department",

                "headcount": {
                    "$addToSet": "$emp_code"
                },

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$in": [
                                    "$attendance.status",
                                    ["PRESENT", "WFH", "ON_DUTY"]
                                ]
                            },
                            {
                                "$cond": [
                                    {
                                        "$eq": [
                                            {
                                                "$ifNull": [
                                                    "$attendance.half_day",
                                                    False
                                                ]
                                            },
                                            True
                                        ]
                                    },
                                    0.5,
                                    1.0
                                ]
                            },
                            0
                        ]
                    }
                },

                "work_hours_values": {
                    "$push": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$attendance.status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {
                                        "$ne": [
                                            "$attendance.work_hours",
                                            None
                                        ]
                                    }
                                ]
                            },
                            "$attendance.work_hours",
                            None
                        ]
                    }
                },

                "late_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$gt": [
                                    {
                                        "$ifNull": [
                                            "$attendance.late_minutes",
                                            0
                                        ]
                                    },
                                    0
                                ]
                            },
                            1,
                            0
                        ]
                    }
                },

                "total_late_minutes": {
                    "$sum": {
                        "$ifNull": [
                            "$attendance.late_minutes",
                            0
                        ]
                    }
                },

                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$eq": [
                                    "$attendance.status",
                                    "LEAVE"
                                ]
                            },
                            1,
                            0
                        ]
                    }
                },

                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$eq": [
                                    "$attendance.status",
                                    "ON_DUTY"
                                ]
                            },
                            1,
                            0
                        ]
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": {
                    "$size": "$headcount"
                },
                "present_days": 1,
                "avg_work_hours": {
                    "$cond": [
                        {
                            "$gt": [
                                {
                                    "$size": {
                                        "$filter": {
                                            "input": "$work_hours_values",
                                            "as": "hours",
                                            "cond": {
                                                "$ne": ["$$hours", None]
                                            }
                                        }
                                    }
                                },
                                0
                            ]
                        },
                        {
                            "$round": [
                                {
                                    "$avg": {
                                        "$filter": {
                                            "input": "$work_hours_values",
                                            "as": "hours",
                                            "cond": {
                                                "$ne": ["$$hours", None]
                                            }
                                        }
                                    }
                                },
                                2
                            ]
                        },
                        None
                    ]
                },
                
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1
            }
        },
        {
            "$sort": {
                "department": 1
            }
        }
    ]

    # 5. Execute aggregation
    try:
        results = list(
            db.employees.aggregate(pipeline)
        )
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database aggregation failed"
        )

    # 6. Return response
    return {
        "month": month,
        "items": results
    }


@app.get("/analytics/leaderboard/late")
def late_attendance_leaderboard(
    month: str,
    limit: int = 10,
    department: Optional[str] = None
):
    if limit < 1:
        raise HTTPException(
            status_code=422,
            detail="limit must be greater than or equal to 1"
        )

    # Keep your existing month validation below this

    # 1. Validate month
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError

        month_start = datetime.strptime(
            month + "-01", "%Y-%m-%d"
        ).date()

        if month_start.strftime("%Y-%m") != month:
            raise ValueError

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format with a valid month"
        )

    # 2. Calculate the first and last date of the month
    if month_start.month == 12:
        next_month = datetime(
            month_start.year + 1, 1, 1
        ).date()
    else:
        next_month = datetime(
            month_start.year,
            month_start.month + 1,
            1
        ).date()

    month_end = next_month - timedelta(days=1)

    # 3. Build MongoDB aggregation pipeline
    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": month_start.isoformat(),
                    "$lte": month_end.isoformat()
                },
                "late_minutes": {"$gt": 0}
            }
        },

        # Group attendance records by employee
        
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {
                    "$sum": {
                        "$ifNull": ["$late_minutes", 0]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$gt": [
                                    {"$ifNull": ["$late_minutes", 0]},
                                    0
                                ]
                            },
                            1,
                            0
                        ]
                    }
                }
            }
        },


        # Connect attendance data with employee details
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },

        # Remove attendance records without an employee
        {
            "$unwind": "$employee"
        }
    ]

    # 4. Apply optional department filter
    if department:
        pipeline.append({
            "$match": {
                "employee.department": department
            }
        })

    # 5. Calculate competition ranking
    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {
                    "total_late_minutes": -1
                },
                "output": {
                    "rank": {
                        "$rank": {}
                    }
                }
            }
        },

        # Include all employees whose rank is within the limit
        {
            "$match": {
                "rank": {"$lte": limit}
            }
        },

        # Sort final results
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },

        # Format response
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        }
    ])

    # 6. Execute aggregation
    try:
        results = list(
            db.attendance_logs.aggregate(pipeline)
        )

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database aggregation failed"
        )

    # 7. Return leaderboard
    return {
        "month": month,
        "limit": limit,
        "department": department,
        "items": results
    }


@app.get(
    "/analytics/departments/{department}/trend",
    responses={
        404: {"description": "Department not found"},
        422: {"description": "Invalid date format or date range"},
        503: {"description": "Database operation failed"}
    }
)
def department_daily_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to")
):
    from decimal import Decimal, ROUND_HALF_UP

    # 1. Validate the date format
    try:
        start_date = datetime.strptime(
            from_date, "%Y-%m-%d"
        ).date()

        end_date = datetime.strptime(
            to_date, "%Y-%m-%d"
        ).date()

        if start_date.isoformat() != from_date:
            raise ValueError

        if end_date.isoformat() != to_date:
            raise ValueError

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Dates must be in YYYY-MM-DD format"
        )

    # 2. Validate date range
    if end_date < start_date:
        raise HTTPException(
            status_code=422,
            detail="to date cannot be earlier than from date"
        )

    if (end_date - start_date).days + 1 > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days"
        )
    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(
            status_code=404,
            detail="Department not found"
        )

    # 3. Convert date boundaries into MongoDB dates
    start_dt = datetime.combine(
        start_date,
        datetime.min.time(),
        tzinfo=timezone.utc
    )

    end_exclusive_dt = datetime.combine(
        end_date + timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone.utc
    )

    # 4. Start with employees belonging to this department.
    # Keep their employee codes and create the first date.
    pipeline = [
        {
            "$match": {
                "department": department
            }
        },
        {
            "$group": {
                "_id": None,
                "employee_codes": {
                    "$addToSet": "$emp_code"
                },
                "date": {
                    "$first": {
                        "$literal": start_dt
                    }
                }
            }
        },

        # 5. Generate one document for every calendar day.
        {
            "$densify": {
                "field": "date",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [
                        start_dt,
                        end_exclusive_dt
                    ]
                }
            }
        },

        # Do not include the exclusive end date.
        {
            "$match": {
                "date": {
                    "$lt": end_exclusive_dt
                }
            }
        },

        # 6. Convert the current date into YYYY-MM-DD.
        {
            "$set": {
                "day_string": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$date",
                        "timezone": "UTC"
                    }
                }
            }
        },

        # 7. Find employees who have joined by this date.
        {
            "$lookup": {
                "from": "employees",
                "let": {
                    "current_day": "$day_string"
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {
                                        "$eq": [
                                            "$department",
                                            department
                                        ]
                                    },
                                    {
                                        "$lte": [
                                            "$joined_on",
                                            "$$current_day"
                                        ]
                                    }
                                ]
                            }
                        }
                    },
                    {
                        "$project": {
                            "_id": 0,
                            "emp_code": 1
                        }
                    }
                ],
                "as": "eligible_employees"
            }
        },

        # 8. Calculate daily headcount.
        {
            "$set": {
                "headcount": {
                    "$size": "$eligible_employees"
                },
                "eligible_codes": {
                    "$map": {
                        "input": "$eligible_employees",
                        "as": "employee",
                        "in": "$$employee.emp_code"
                    }
                }
            }
        },

        # 9. Find attendance records for this department and date.
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {
                    "current_day": "$day_string",
                    "codes": "$eligible_codes"
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {
                                        "$eq": [
                                            "$date",
                                            "$$current_day"
                                        ]
                                    },
                                    {
                                        "$in": [
                                            "$emp_code",
                                            "$$codes"
                                        ]
                                    }
                                ]
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,

                            "present_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$in": [
                                                "$status",
                                                [
                                                    "PRESENT",
                                                    "WFH",
                                                    "ON_DUTY"
                                                ]
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {
                                                    "$eq": [
                                                        {
                                                            "$ifNull": [
                                                                "$half_day",
                                                                False
                                                            ]
                                                        },
                                                        True
                                                    ]
                                                },
                                                0.5,
                                                1.0
                                            ]
                                        },
                                        0
                                    ]
                                }
                            },

                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$gt": [
                                                {
                                                    "$ifNull": [
                                                        "$late_minutes",
                                                        0
                                                    ]
                                                },
                                                0
                                            ]
                                        },
                                        1,
                                        0
                                    ]
                                }
                            }
                        }
                    }
                ],
                "as": "daily_attendance"
            }
        },

        # 10. Extract daily attendance values.
        # Missing attendance records become zero.
        {
            "$set": {
                "present_count": {
                    "$ifNull": [
                        {
                            "$arrayElemAt": [
                                "$daily_attendance.present_count",
                                0
                            ]
                        },
                        0
                    ]
                },
                "late_count": {
                    "$ifNull": [
                        {
                            "$arrayElemAt": [
                                "$daily_attendance.late_count",
                                0
                            ]
                        },
                        0
                    ]
                },

                # MongoDB dayOfWeek:
                # Sunday = 1, Monday = 2, ..., Saturday = 7.
                "day_number": {
                    "$dayOfWeek": "$date"
                }
            }
        },

        # 11. Identify weekdays.
        {
            "$set": {
                "is_working_day": {
                    "$and": [
                        {
                            "$gte": [
                                "$day_number",
                                2
                            ]
                        },
                        {
                            "$lte": [
                                "$day_number",
                                6
                            ]
                        }
                    ]
                }
            }
        },

        # 12. Calculate attendance rate.
        # Use truncation after adding 0.5 to achieve
        # ROUND_HALF_UP to four decimal places.
{
    "$set": {
        "attendance_rate": {
            "$cond": [
                # CONDITION
                {
                    "$and": [
                        "$is_working_day",
                        {"$gt": ["$headcount", 0]}
                    ]
                },

                # VALUE IF CONDITION IS TRUE
                {
                    "$divide": [
                        {
                            "$trunc": {
                                "$add": [
                                    {
                                        "$multiply": [
                                            {
                                                "$divide": [
                                                    {
                                                        "$multiply": [
                                                            "$present_count",
                                                            100
                                                        ]
                                                    },
                                                    "$headcount"
                                                ]
                                            },
                                            10000
                                        ]
                                    },
                                    0.5
                                ]
                            }
                        },
                        10000
                    ]
                },

                # VALUE IF CONDITION IS FALSE
                None
            ]
        }
    }
},


        # 13. Calculate the seven-day moving average.
        # Current date and previous six calendar dates.
        {
            "$setWindowFields": {
                "sortBy": {
                    "date": 1
                },
                "output": {
                    "moving_avg_raw": {
                        "$avg": "$attendance_rate",
                        "window": {
                            "documents": [
                                -6,
                                0
                            ]
                        }
                    }
                }
            }
        },

        # 14. Round moving average to four decimals,
        # using ROUND_HALF_UP.
        {
            "$set": {
                "moving_avg_7d": {
                    "$cond": [
                        {
                            "$ne": [
                                "$moving_avg_raw",
                                None
                            ]
                        },
                        {
                            "$divide": [
                                {
                                    "$trunc": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    "$moving_avg_raw",
                                                    10000
                                                ]
                                            },
                                            0.5
                                        ]
                                    }
                                },
                                10000
                            ]
                        },
                        None
                    ]
                }
            }
        },

        # 15. Format the final API response.
        {
            "$project": {
                "_id": 0,
                "date": "$day_string",
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1
            }
        },

        {
            "$sort": {
                "date": 1
            }
        }
    ]

    # 16. Execute MongoDB aggregation.
    try:
        results = list(
            db.employees.aggregate(pipeline)
        )

    except PyMongoError as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )

    # 17. An unknown department has no employee documents.
    if not results:
        raise HTTPException(
            status_code=404,
            detail="Department not found"
        )

    # 18. Return the daily trend.
    return {
        "department": department,
        "from": from_date,
        "to": to_date,
        "items": results
    }


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(10, ge=1),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to")
):
    # --------------------------------------------------
    # 1. Check whether the requested endpoint is supported
    # --------------------------------------------------

    allowed_endpoints = [
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend"
    ]

    if endpoint not in allowed_endpoints:
        raise HTTPException(
            status_code=422,
            detail="Unsupported explain endpoint"
        )

    # --------------------------------------------------
    # 2. Helper: validate YYYY-MM format
    # --------------------------------------------------

    def validate_month(value):
        try:
            if not value or len(value) != 7 or value[4] != "-":
                raise ValueError

            parsed = datetime.strptime(
                value + "-01",
                "%Y-%m-%d"
            )

            if parsed.strftime("%Y-%m") != value:
                raise ValueError

            return parsed.date()

        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="month must be in YYYY-MM format with a valid month"
            )

    # --------------------------------------------------
    # 3. Helper: calculate month boundaries
    # --------------------------------------------------

    def get_month_range(value):
        start = validate_month(value)

        if start.month == 12:
            next_month = datetime(
                start.year + 1, 1, 1
            ).date()
        else:
            next_month = datetime(
                start.year,
                start.month + 1,
                1
            ).date()

        end = next_month - timedelta(days=1)

        return start.isoformat(), end.isoformat()

    # --------------------------------------------------
    # 4. Prepare MongoDB query based on endpoint
    # --------------------------------------------------

    collection = None
    query = {}
    sort = None
    skip = 0
    result_limit = None
    pipeline = None

    # A. Attendance list
    if endpoint == "attendance_list":

        if date_from:
            try:
                parsed = datetime.strptime(
                    date_from, "%Y-%m-%d"
                )

                if parsed.strftime("%Y-%m-%d") != date_from:
                    raise ValueError

            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail="date_from must be in YYYY-MM-DD format"
                )

        if date_to:
            try:
                parsed = datetime.strptime(
                    date_to, "%Y-%m-%d"
                )

                if parsed.strftime("%Y-%m-%d") != date_to:
                    raise ValueError

            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail="date_to must be in YYYY-MM-DD format"
                )

        if date_from and date_to and date_from > date_to:
            raise HTTPException(
                status_code=422,
                detail="date_from cannot be greater than date_to"
            )

        allowed_statuses = [
            "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
        ]

        if status and status not in allowed_statuses:
            raise HTTPException(
                status_code=422,
                detail="Invalid attendance status"
            )

        collection = "attendance_logs"

        query = build_attendance_filter(
            emp_code=emp_code,
            date_from=date_from,
            date_to=date_to,
            status=status
        )

        sort = {
            "date": -1,
            "emp_code": 1
        }

        skip = (page - 1) * page_size
        result_limit = page_size

    # B. Employee monthly analytics
    elif endpoint == "employee_monthly":

        if not emp_code:
            raise HTTPException(
                status_code=422,
                detail="emp_code is required"
            )

        month_start, month_end = get_month_range(month)

        collection = "attendance_logs"

        query = {
            "emp_code": emp_code,
            "date": {
                "$gte": month_start,
                "$lte": month_end
            }
        }

        sort = {
            "date": 1
        }
        
        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {
                        "$gte": month_start,
                        "$lte": month_end
                    }
                }
            },
            {
                "$addFields": {
                    "weekday": {
                        "$dayOfWeek": {
                            "$dateFromString": {
                                "dateString": "$date"
                            }
                        }
                    }
                }
            },
            {
                "$group": {
                    "_id": None,
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"]
                                            ]
                                        },
                                        {"$gte": ["$weekday", 2]},
                                        {"$lte": ["$weekday", 6]}
                                    ]
                                },
                                {
                                    "$cond": [
                                        {
                                            "$eq": [
                                                {"$ifNull": ["$half_day", False]},
                                                True
                                            ]
                                        },
                                        0.5,
                                        1.0
                                    ]
                                },
                                0
                            ]
                        }
                    },
                    "leave_days": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$status", "LEAVE"]},
                                1,
                                0
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$gt": [
                                        {"$ifNull": ["$late_minutes", 0]},
                                        0
                                    ]
                                },
                                1,
                                0
                            ]
                        }
                    }
                }
            }
        ]



    # C. Department summary
    elif endpoint == "department_summary":

        month_start, month_end = get_month_range(month)

        collection = "employees"

        query = {
            "joined_on": {
                "$lte": month_end
            }
        }

        if department:
            query["department"] = department

        sort = {
            "department": 1
        }
        
        
        
        pipeline = [
            {
                "$match": query
            },
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {
                        "employee_code": "$emp_code"
                    },
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {
                                            "$eq": [
                                                "$emp_code",
                                                "$$employee_code"
                                            ]
                                        },
                                        {
                                            "$gte": [
                                                "$date",
                                                month_start
                                            ]
                                        },
                                        {
                                            "$lte": [
                                                "$date",
                                                month_end
                                            ]
                                        }
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "attendance"
                }
            },
            {
                "$unwind": {
                    "path": "$attendance",
                    "preserveNullAndEmptyArrays": True
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "headcount": {
                        "$addToSet": "$emp_code"
                    },
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$in": [
                                        "$attendance.status",
                                        ["PRESENT", "WFH", "ON_DUTY"]
                                    ]
                                },
                                {
                                    "$cond": [
                                        {
                                            "$eq": [
                                                {
                                                    "$ifNull": [
                                                        "$attendance.half_day",
                                                        False
                                                    ]
                                                },
                                                True
                                            ]
                                        },
                                        0.5,
                                        1
                                    ]
                                },
                                0
                            ]
                        }
                    },
                    "work_hours_values": {
                        "$push": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$attendance.status",
                                                ["PRESENT", "WFH", "ON_DUTY"]
                                            ]
                                        },
                                        {
                                            "$ne": [
                                                "$attendance.work_hours",
                                                None
                                            ]
                                        }
                                    ]
                                },
                                "$attendance.work_hours",
                                None
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$gt": [
                                        {
                                            "$ifNull": [
                                                "$attendance.late_minutes",
                                                0
                                            ]
                                        },
                                        0
                                    ]
                                },
                                1,
                                0
                            ]
                        }
                    },
                    "total_late_minutes": {
                        "$sum": {
                            "$ifNull": [
                                "$attendance.late_minutes",
                                0
                            ]
                        }
                    },
                    "leave_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$eq": [
                                        "$attendance.status",
                                        "LEAVE"
                                    ]
                                },
                                1,
                                0
                            ]
                        }
                    },
                    "on_duty_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$eq": [
                                        "$attendance.status",
                                        "ON_DUTY"
                                    ]
                                },
                                1,
                                0
                            ]
                        }
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "department": "$_id",
                    "headcount": {
                        "$size": "$headcount"
                    },
                    "present_days": 1,
                    "avg_work_hours": {
                        "$cond": [
                            {
                                "$gt": [
                                    {
                                        "$size": {
                                            "$filter": {
                                                "input": "$work_hours_values",
                                                "as": "hours",
                                                "cond": {
                                                    "$ne": ["$$hours", None]
                                                }
                                            }
                                        }
                                    },
                                    0
                                ]
                            },
                            {
                                "$round": [
                                    {
                                        "$avg": {
                                            "$filter": {
                                                "input": "$work_hours_values",
                                                "as": "hours",
                                                "cond": {
                                                    "$ne": ["$$hours", None]
                                                }
                                            }
                                        }
                                    },
                                    2
                                ]
                            },
                            None
                        ]
                    },
                    "late_count": 1,
                    "total_late_minutes": 1,
                    "leave_count": 1,
                    "on_duty_count": 1
                }
            },
            {
                "$sort": {
                    "department": 1
                }
            }
        ]


        



    # D. Late leaderboard
    elif endpoint == "late_leaderboard":

        month_start, month_end = get_month_range(month)

        collection = "attendance_logs"

        query = {
            "date": {
                "$gte": month_start,
                "$lte": month_end
            },
            "late_minutes": {
                "$gt": 0
            }
        }

        sort = {
            "date": -1,
            "emp_code": 1
        }

        pipeline = [
            {
                "$match": query
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {
                        "$sum": {
                            "$ifNull": ["$late_minutes", 0]
                        }
                    }
                }
            },
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "_id",
                    "foreignField": "emp_code",
                    "as": "employee"
                }
            },
            {
                "$unwind": "$employee"
            }
        ]

        if department:
            pipeline.append({
                "$match": {
                    "employee.department": department
                }
            })

        pipeline.extend([
            {
                "$setWindowFields": {
                    "sortBy": {
                        "total_late_minutes": -1
                    },
                    "output": {
                        "rank": {
                            "$rank": {}
                        }
                    }
                }
            },
            {
                "$match": {
                    "rank": {
                        "$lte": limit
                    }
                }
            },
            {
                "$sort": {
                    "total_late_minutes": -1,
                    "_id": 1
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "rank": 1,
                    "emp_code": "$_id",
                    "name": "$employee.name",
                    "department": "$employee.department",
                    "total_late_minutes": 1
                }
            }
        ])

    # E. Department daily trend
    elif endpoint == "department_trend":

        if not department:
            raise HTTPException(
                status_code=422,
                detail="department is required"
            )

        if not from_date or not to_date:
            raise HTTPException(
                status_code=422,
                detail="from and to dates are required"
            )

        for value, field_name in [
            (from_date, "from"),
            (to_date, "to")
        ]:
            try:
                parsed = datetime.strptime(
                    value, "%Y-%m-%d"
                )

                if parsed.strftime("%Y-%m-%d") != value:
                    raise ValueError

            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field_name} must be in YYYY-MM-DD format"
                )

        if from_date > to_date:
            raise HTTPException(
                status_code=422,
                detail="to date cannot be earlier than from date"
            )

        start = datetime.strptime(
            from_date, "%Y-%m-%d"
        ).date()

        end = datetime.strptime(
            to_date, "%Y-%m-%d"
        ).date()

        if (end - start).days + 1 > 92:
            raise HTTPException(
                status_code=422,
                detail="Date range cannot exceed 92 days"
            )

        collection = "employees"

        query = {
            "department": department
        }

        sort = {
            "emp_code": 1
        }
        
        
        start_dt = datetime.combine(
            start,
            datetime.min.time(),
            tzinfo=timezone.utc
        )

        end_exclusive_dt = datetime.combine(
            end + timedelta(days=1),
            datetime.min.time(),
            tzinfo=timezone.utc
        )


        pipeline = [
            {
                "$match": {
                    "department": department
                }
            },
            
            {
                "$group": {
                    "_id": None,
                    "employee_codes": {
                        "$addToSet": "$emp_code"
                    },
                    "date": {
                        "$first": {
                            "$literal": start_dt
                        }
                    }
                }
            },

            {
                "$densify": {
                    "field": "date",
                    "range": {
                        "step": 1,
                        "unit": "day",
                        "bounds": [
                            start_dt,
                            end_exclusive_dt
                        ]
                    }
                }
            },
            {
                "$match": {
                    "date": {
                        "$lt": end_exclusive_dt
                    }
                }
            },
            
            {
                "$set": {
                    "day_string": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$date",
                            "timezone": "UTC"
                        }
                    }
                }
            }

        ]
        
        
        pipeline.extend([
            {
                "$lookup": {
                    "from": "employees",
                    "let": {"current_day": "$day_string"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$department", department]},
                                        {"$lte": ["$joined_on", "$$current_day"]}
                                    ]
                                }
                            }
                        },
                        {"$project": {"_id": 0, "emp_code": 1}}
                    ],
                    "as": "eligible_employees"
                }
            },
            {
                "$set": {
                    "headcount": {"$size": "$eligible_employees"},
                    "eligible_codes": {
                        "$map": {
                            "input": "$eligible_employees",
                            "as": "employee",
                            "in": "$$employee.emp_code"
                        }
                    }
                }
            },
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {
                        "current_day": "$day_string",
                        "codes": "$eligible_codes"
                    },
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$date", "$$current_day"]},
                                        {"$in": ["$emp_code", "$$codes"]}
                                    ]
                                }
                            }
                        },
                        {
                            "$group": {
                                "_id": None,
                                "present_count": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$in": [
                                                    "$status",
                                                    ["PRESENT", "WFH", "ON_DUTY"]
                                                ]
                                            },
                                            {
                                                "$cond": [
                                                    {"$eq": [{"$ifNull": ["$half_day", False]}, True]},
                                                    0.5,
                                                    1.0
                                                ]
                                            },
                                            0
                                        ]
                                    }
                                },
                                "late_count": {
                                    "$sum": {
                                        "$cond": [
                                            {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                                            1,
                                            0
                                        ]
                                    }
                                }
                            }
                        }
                    ],
                    "as": "daily_attendance"
                }
            },
            {
                "$set": {
                    "present_count": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$daily_attendance.present_count", 0]},
                            0
                        ]
                    },
                    "late_count": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$daily_attendance.late_count", 0]},
                            0
                        ]
                    },
                    "day_number": {"$dayOfWeek": "$date"}
                }
            },
            {
                "$set": {
                    "is_working_day": {
                        "$and": [
                            {"$gte": ["$day_number", 2]},
                            {"$lte": ["$day_number", 6]}
                        ]
                    }
                }
            },
            {
                "$set": {
                    "attendance_rate": {
                        "$cond": [
                            {
                                "$and": [
                                    "$is_working_day",
                                    {"$gt": ["$headcount", 0]}
                                ]
                            },
                            {
                                "$divide": [
                                    {
                                        "$trunc": {
                                            "$add": [
                                                {
                                                    "$multiply": [
                                                        {
                                                            "$divide": [
                                                                {"$multiply": ["$present_count", 100]},
                                                                "$headcount"
                                                            ]
                                                        },
                                                        10000
                                                    ]
                                                },
                                                0.5
                                            ]
                                        }
                                    },
                                    10000
                                ]
                            },
                            None
                        ]
                    }
                }
            },
            {
                "$setWindowFields": {
                    "sortBy": {"date": 1},
                    "output": {
                        "moving_avg_raw": {
                            "$avg": "$attendance_rate",
                            "window": {"documents": [-6, 0]}
                        }
                    }
                }
            },
            {
                "$set": {
                    "moving_avg_7d": {
                        "$cond": [
                            {"$ne": ["$moving_avg_raw", None]},
                            {
                                "$divide": [
                                    {
                                        "$trunc": {
                                            "$add": [
                                                {"$multiply": ["$moving_avg_raw", 10000]},
                                                0.5
                                            ]
                                        }
                                    },
                                    10000
                                ]
                            },
                            None
                        ]
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "date": "$day_string",
                    "is_working_day": 1,
                    "headcount": 1,
                    "present_count": 1,
                    "late_count": 1,
                    "attendance_rate": 1,
                    "moving_avg_7d": 1
                }
            },
            {"$sort": {"date": 1}}
        ])




    # --------------------------------------------------
    # 5. Execute MongoDB explain
    # --------------------------------------------------

    
    if pipeline is not None:
        explain_command = {
            "aggregate": collection,
            "pipeline": pipeline,
            "cursor": {}
        }
    else:
        explain_command = {
            "find": collection,
            "filter": query
        }


    
    if pipeline is None:
        if sort:
            explain_command["sort"] = sort

        if skip:
            explain_command["skip"] = skip

        if result_limit is not None:
            explain_command["limit"] = result_limit


    try:
        result = db.command(
            "explain",
            explain_command,
            verbosity="executionStats"
        )

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="MongoDB explain operation failed"
        )

    # --------------------------------------------------
    # 6. Return query plan and execution statistics
    # --------------------------------------------------

    
    query_planner = result.get("queryPlanner")
    execution_stats = result.get("executionStats")
    return {
        "endpoint": endpoint,
        "collection": collection,
        "explain": result
    }



# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
