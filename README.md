# \# Employee Attendance \& Analytics API

# 

# \## Project Overview

# 

# A REST API built using FastAPI and MongoDB to manage employee attendance, punch-in and punch-out operations, manual attendance corrections, and attendance analytics.

# 

# \## Technologies Used

# 

# \- Python 3.11+

# \- FastAPI

# \- MongoDB

# \- PyMongo

# \- Pydantic

# \- Uvicorn

# 

# \## Project Structure

# 

# ```text

# candidate\_kit/

# ├── app/

# │   ├── \_\_init\_\_.py

# │   └── main.py

# ├── sample\_data/

# │   ├── employees.json

# │   └── attendance\_logs.json

# ├── tests/

# ├── openapi.yaml

# ├── requirements.txt

# ├── sample\_seed.py

# ├── README.md

# ├── REVIEW.md

# ├── DECISIONS.md

# ├── DATA\_MODEL.md

# └── PROBLEM\_STATEMENT.docx

# ```

# 

# \## Prerequisites

# 

# \- Python 3.11 or newer

# \- MongoDB 6.0 or newer

# \- pip

# 

# \## Installation and Setup

# 

# \### 1. Clone the repository

# 

# ```bash

# git clone https://github.com/Navyabattu0102/hrone-attendance-analytics-api.git

# cd hrone-attendance-analytics-api

# ```

# 

# \### 2. Create and activate a virtual environment

# 

# Windows CMD:

# 

# ```cmd

# python -m venv .venv

# .venv\\Scripts\\activate

# ```

# 

# \### 3. Install dependencies

# 

# ```cmd

# pip install -r requirements.txt

# ```

# 

# \### 4. Configure MongoDB

# 

# Set the MongoDB connection URI and database name using environment variables.

# 

# Windows CMD with a local MongoDB instance:

# 

# ```cmd

# set MONGO\_URI=mongodb://localhost:27017

# set MONGO\_DB=attendance\_db

# ```

# 

# For MongoDB Atlas, set `MONGO\_URI` to your Atlas connection string. Keep credentials private and do not commit them to GitHub.

# 

# If your application uses a `.env` file, configure the same variables there according to the implementation in `app/main.py`.

# 

# \### 5. Start the application

# 

# ```cmd

# uvicorn app.main:app --port 8000

# ```

# 

# \## API Documentation

# 

# After the application starts, access:

# 

# \- \*\*Swagger UI:\*\* http://127.0.0.1:8000/docs

# \- \*\*OpenAPI JSON:\*\* http://127.0.0.1:8000/openapi.json

# \- \*\*Health check:\*\* http://127.0.0.1:8000/health

# 

# \## Implemented Features

# 

# \- Employee creation and listing

# \- Attendance punch-in and punch-out

# \- Attendance regularization with correction history

# \- Attendance listing with filtering and pagination

# \- Employee monthly analytics

# \- Department summary

# \- Late attendance leaderboard

# \- Department daily attendance trends

# \- MongoDB query execution-plan inspection

# \- MongoDB indexes and duplicate-record protection

# 

# \## Database

# 

# The application uses MongoDB collections for employee records and attendance logs.

# 

# Indexes are created by the application to support data integrity and common queries.

# 

# \## Documentation

# 

# \- `openapi.yaml`: API contract defining endpoints, parameters, responses, and validation requirements.

# \- `REVIEW.md`: Review of defects identified in the starter implementation.

# \- `DECISIONS.md`: Technical decisions and design explanations.

# \- `DATA\_MODEL.md`: Database model and collection details.

# \- `sample\_seed.py`: Sample data seeding utility.

# 

# \## Security Notes

# 

# \- Do not commit `.env` files, database credentials, or other secrets.

# \- Keep virtual environments and Python cache files out of version control.

# \- Use environment variables to configure database connections.

# 

# \## Running Tests

# 

# Run the project's available tests from the repository root:

# 

# ```cmd

# pytest

# ```

# 

# Ensure the required dependencies and MongoDB configuration are available before running tests.

