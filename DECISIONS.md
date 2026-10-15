# REVIEW.md

## Defects found in the starter code

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `compute_late_minutes()` | The original helper does not correctly handle timezone-aware timestamps and IST shift calculations. | Test a punch-in close to the shift start using UTC and IST timestamps. | Added timestamp normalization and IST-based calculations. |
| 2 | `compute_work_hours()` | Python's built-in `round()` uses banker's rounding, but the contract requires half-up rounding to two decimal places. | Test a duration whose third decimal digit is exactly 5. | Used explicit half-up rounding. |
| 3 | `compute_overtime()` | The original implementation assumes the shift ends on the same calendar date, which fails for overnight shifts. | Test a shift ending after midnight. | Added overnight-aware shift-end calculation and whole-minute overtime handling. |
| 4 | `create_employee()` | Checking for an existing employee before insertion is not sufficient to prevent duplicate employee codes under concurrent requests. | Send two simultaneous requests with the same `emp_code`. | Added a unique MongoDB index and duplicate-key handling. |
| 5 | `list_employees()` | Pagination uses `page * page_size` as the skip value, so page 1 skips the first page of records. | Request page 1 and compare it with the first employee records. | Changed skip calculation to `(page - 1) * page_size`. |
| 6 | `list_employees()` | The total count ignores the department filter. | Request employees from one department and compare `total` with the filtered result count. | Applied the same filter to `count_documents()`. |
| 7 | `list_employees()` | Pagination parameters are not properly validated or restricted to the contract's maximum page size. | Try page 0, a negative page size, or page size greater than 100. | Added query parameter validation. |
| 8 | `punch_in()` | The employee lookup result is not checked before accessing the employee's shift information. | Punch in using an unknown employee code. | Added employee existence validation and a 404 response. |
| 9 | `punch_in()` | The original duplicate-record check followed by insertion is vulnerable to concurrent requests. | Send simultaneous punch-in requests for the same employee and date. | Added a unique compound index on `emp_code` and `date`, and handled duplicate-key errors. |
| 10 | `punch_in()` | The original timestamp conversion uses the machine's local timezone rather than consistently applying the API's UTC/IST rules. | Submit an epoch-millisecond timestamp near midnight UTC. | Added UTC timestamp normalization and IST attendance-date calculation. |
| 11 | `punch_in()` | The original code does not properly validate the employee's existence and attendance status before creating a record. | Use an unknown employee code or an unsupported status. | Added request validation and appropriate error responses. |
| 12 | `list_attendance()` | The original implementation fetches all matching documents and sorts and paginates them in Python. This is inefficient for a large collection. | Test against a large attendance collection and inspect database query behavior. | Moved filtering, sorting, counting, and pagination into MongoDB queries backed by indexes. |
| 13 | `list_attendance()` | The original pagination and response handling do not consistently enforce the API's pagination and response contract. | Test page 1, page 2, maximum page size, and filtered totals. | Added validated pagination and consistent response formatting. |

## Things examined and decided were not defects

- The 10-minute grace period itself was correct in principle: lateness should apply only when the delay is strictly greater than 10 minutes.
- The default page size of 20 was correct; the issue was pagination calculation and validation.
- The use of MongoDB collections named `employees` and `attendance_logs` matched the supplied data model.
- The health endpoint returning `{"status": "ok"}` was appropriate for the health check contract.