# 

# \# Technical Decisions

# 

# \## 1. Follow the API contract

# The supplied `openapi.yaml` is the source of truth for endpoint paths, request and response fields, HTTP status codes, validation, and business rules. The implementation is kept in `app/main.py` as required.

# 

# \## 2. Handle timestamps consistently

# API timestamps use epoch milliseconds. MongoDB stores instants as UTC datetimes, while shift calculations and attendance dates use IST. Timestamps are truncated to whole seconds before calculations and storage.

# 

# \## 3. Enforce uniqueness in MongoDB

# Unique indexes protect employee codes and the combination of employee code and attendance date. Duplicate-key errors are translated into appropriate HTTP conflict responses.

# 

# \## 4. Calculate attendance values consistently

# Work hours use two-decimal half-up rounding. Late minutes follow the ten-minute grace-period rule, overtime follows the thirty-minute threshold, and half-day status is determined from rounded work hours.

# 

# \## 5. Use database-side filtering and pagination

# Employee and attendance listings apply filters, sorting, counts, and pagination in MongoDB. Pagination starts at page 1 and limits page size to 100.

# 

# \## 6. Use aggregation pipelines for analytics

# Analytics calculations are performed in MongoDB aggregation pipelines. Stored attendance values are used according to the supplied data model, and employee headcount includes eligible employees without attendance logs.

# 

# \## 7. Preserve correction history

# Attendance regularization records only actual changes and appends an audit entry containing the timestamp, person making the correction, reason, and changed values.

# 

# \## 8. Create indexes at startup

# Required indexes are created when the application starts. Index creation uses stable names and specifications so repeated startup does not create duplicate indexes.

# 

# \## 9. Validate inputs and return appropriate errors

# Request models validate fields and timestamps. The API returns suitable validation, not-found, conflict, and database-error responses according to the contract.

# 

