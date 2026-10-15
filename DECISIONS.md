# Technical Decisions

## 1\. Follow the API Contract

The supplied openapi.yaml is the source of truth for endpoint paths, request and response fields, HTTP status codes, validation, and business rules. The implementation is maintained in app/main.py.

## 2\. Handle Timestamps Consistently

API timestamps use epoch milliseconds. MongoDB stores instants as UTC datetimes, while shift calculations and attendance dates use IST. Timestamps are truncated to whole seconds before calculations and storage.

## 3\. Enforce Uniqueness in MongoDB

Unique indexes protect employee codes and the combination of employee code and attendance date. Duplicate-key errors are translated into appropriate HTTP conflict responses.

## 4\. Calculate Attendance Values Consistently

Work hours use two-decimal rounding. Late minutes, overtime, and half-day status follow the attendance rules implemented in the application and specified by the assignment.

## 5\. Keep Configuration and Secrets Separate

Database connection settings are configured through environment variables. The .env file is excluded from Git to avoid committing local configuration and secrets.

## 6\. Support Query Performance Inspection

MongoDB indexes support common attendance and analytics queries. Explain-plan endpoints allow query execution plans and index usage to be inspected.

