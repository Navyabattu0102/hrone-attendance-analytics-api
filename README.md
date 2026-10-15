# Employee Attendance \& Analytics API

## Project Overview

A REST API built using FastAPI and MongoDB to manage employee attendance, punch-in and punch-out operations, manual attendance corrections, and attendance analytics.

## Technologies Used

* Python 3.11+
* FastAPI
* MongoDB 6.0+
* PyMongo
* Pydantic
* Uvicorn

## Project Structure

```text
candidate\_kit/
│
├── app/
│   ├── \_\_init\_\_.py
│   └── main.py
│
├── requirements.txt
├── README.md
├── REVIEW.md
├── DECISIONS.md
├── sample\_seed.py
└── sample\_data/
```

## Prerequisites

* Python 3.11 or newer
* MongoDB 6.0 or newer
* pip

## Installation and Setup

1. Clone the repository.

```bash
git clone https://github.com/Navyabattu0102/hrone-attendance-analytics-api.git
cd hrone-attendance-analytics-api
```

2. Create and activate a virtual environment.

Windows CMD:

```cmd
python -m venv .venv
.venv\\Scripts\\activate
```

3. Install dependencies.

```cmd
pip install -r requirements.txt
```

4. Configure MongoDB environment variables.

Windows CMD:

```cmd
set MONGO\_URI=mongodb://localhost:27017
set MONGO\_DB=attendance\_db
```

For MongoDB Atlas, set `MONGO\_URI` to your MongoDB connection string.

5. Start the application.

```cmd
uvicorn app.main:app --port 8000
```

## API Documentation

After starting the application, open:

* Swagger UI: http://127.0.0.1:8000/docs
* OpenAPI JSON: http://127.0.0.1:8000/openapi.json
* Health check: http://127.0.0.1:8000/health

## Implemented Features

* Employee creation and listing
* Attendance punch-in and punch-out
* Attendance regularization with correction history
* Attendance listing with filters and pagination
* Employee monthly analytics
* Department summary
* Late attendance leaderboard
* Department daily attendance trend
* MongoDB execution plan explanation
* MongoDB indexes and duplicate-record protection

## Database

The application uses two MongoDB collections:

* `employees`
* `attendance\_logs`

MongoDB indexes are created automatically when the application starts.

## Documentation

* `REVIEW.md`: Review of defects identified in the starter implementation.
* `DECISIONS.md`: Technical decisions and design explanations.

## Notes

Do not commit `.env` files, database credentials, secrets, virtual environments, or other sensitive configuration to the public repository.

