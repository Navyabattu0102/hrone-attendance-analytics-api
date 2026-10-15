# REVIEW.md

## Defects Found in the Starter `app/main.py`

The following defects were identified while reviewing the starter implementation. They were checked against the expected API behaviour and corrected in the final implementation.

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `compute_late_minutes()` | The helper does not correctly handle overnight shifts because it constructs the shift start using the punch-in date without considering the previous day. | Test an employee whose shift starts at 22:00 and whose punch-in occurs after midnight. The late calculation can be incorrect. | Added correct shift-time and date handling using the appropriate timezone and shift start. |
| 2 | `compute_late_minutes()` | The starter implementation does not explicitly handle the required timezone interpretation consistently. | Pass timestamps representing the same instant in different timezone representations and compare the late-minute calculation. | Standardized timestamp and IST handling before calculating lateness. |
| 3 | `compute_work_hours()` | Python's built-in `round()` uses banker's rounding, which may not match the required half-up rounding behaviour. | Test work durations whose calculated hours have a value exactly halfway between two hundredths. | Implemented the required two-decimal half-up rounding. |
| 4 | `compute_overtime()` | The shift-end calculation assumes the shift ends on the same date. This fails for overnight shifts. | Test a shift from 22:00 to 06:00 with a punch-out after midnight. | Added correct handling of overnight shift end times. |
| 5 | `compute_overtime()` | The starter implementation does not enforce the minimum 30-minute overtime requirement. | Test punch-outs 10, 29, 30, and 31 minutes after shift end. | Overtime is counted only when it reaches the required 30-minute threshold, using whole minutes. |
| 6 | `create_employee()` | Duplicate employee checking is performed before insertion without a unique database constraint. Concurrent requests can both pass the check and insert duplicate employee codes. | Send concurrent requests to create employees with the same `emp_code`. | Added a unique index on `emp_code` and handled duplicate-key errors. |
| 7 | `create_employee()` | `created_at` is stored using naive local datetime instead of a consistent timezone-aware timestamp. | Inspect the stored MongoDB document and compare timestamps across environments with different local timezones. | Standardized timestamp handling and storage. |
| 8 | `GET /employees` | Pagination uses `page * page_size` for the skip value. This causes the first page to skip the first page of records. | Request page 1 with a page size of 10. The first 10 employees may be skipped. | Corrected the skip calculation to `(page - 1) * page_size`. |
| 9 | `GET /employees` | The total count does not apply the search filter, so the returned total can be incorrect when searching. | Search using `q` and compare the returned total with the number of matching employees. | Applied the same filter when calculating the total count. |
| 10 | `GET /employees` | Pagination parameters are not sufficiently validated. Invalid page numbers or excessively large page sizes can produce incorrect or inefficient requests. | Try page 0, a negative page number, or a page size greater than 100. | Added pagination validation with the required limits. |
| 11 | `POST /attendance/punch-in` | The employee lookup result is not checked before accessing employee fields. An unknown employee can cause an internal server error. | Punch in using an `emp_code` that does not exist. | Check whether the employee exists and return a 404 response when missing. |
| 12 | `POST /attendance/punch-in` | The timestamp is converted using the server's local timezone rather than a consistent UTC/IST interpretation. | Submit a known epoch-millisecond timestamp and compare the resulting attendance date with the expected IST date. | Standardized timestamp conversion and attendance-date calculation using IST. |
| 13 | `POST /attendance/punch-in` | Checking for an existing attendance record before inserting is not sufficient to prevent concurrent duplicate records. | Send simultaneous punch-in requests for the same employee and attendance date. | Added a unique compound index on `(emp_code, date)` and handled duplicate-key errors. |
| 14 | `POST /attendance/punch-in` | The starter implementation does not sufficiently validate the attendance status against the allowed values. | Submit an unsupported attendance status. | Added request validation for permitted status values. |
| 15 | `GET /attendance` | The starter implementation retrieves matching attendance records and performs sorting and pagination in Python. This is inefficient for large datasets. | Test with a large attendance collection, such as 100,000 records, and observe memory usage and response time. | Moved filtering, sorting, and pagination to MongoDB queries and added supporting indexes. |
| 16 | `GET /attendance` | The starter response exposes MongoDB's internal `_id` as an API identifier, although the required attendance response should not expose an attendance ID. | Inspect the returned attendance JSON and check for an `id` field. | Standardized the attendance response to expose only the fields required by the API contract. |

## Items Reviewed and Considered Not to Be Defects

| Item | Why it is not a defect |
|---|---|
| Using MongoDB for employee and attendance storage | MongoDB is the required database for the assignment. |
| Using `find_one()` for an employee lookup | It is appropriate when retrieving one employee using a unique employee code. |
| Using a unique index for employee codes | This is the correct way to enforce uniqueness at the database level, including concurrent requests. |
| Using a compound unique index for employee attendance | It correctly enforces one attendance record per employee per attendance date. |
| Returning HTTP 201 for employee creation and punch-in | HTTP 201 Created is appropriate for operations that create a resource. |
| Returning HTTP 200 for punch-out | Punch-out updates an existing attendance record, so HTTP 200 is appropriate. |
| Returning HTTP 422 for invalid request data | This is the expected FastAPI validation response for invalid request input. |

## Conclusion

The starter implementation had issues involving date and timezone handling, overnight shifts, rounding, duplicate prevention, pagination, validation, and database query efficiency.

These issues were addressed in the final implementation while following the API requirements and MongoDB data model.