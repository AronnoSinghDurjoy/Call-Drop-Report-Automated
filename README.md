# Call-Drop-Report-Automated
This portal Helps to Send Report Of Call drop For every month and Selective Date range automatically.

# Call Drop Report Generator

A Flask-based web application to generate monthly call drop reports from Oracle Database, package them as Excel and ZIP files, and email them to multiple recipients. The app also supports scheduling automated monthly report generation and email delivery.

---

## Features

- Connects to Oracle Database to run predefined SQL queries.
- Generates three types of reports:
  - Customer-wise Off Net Call Drop Report
  - Customer-wise On Net Call Drop Report
  - Day-wise Call Drop Report
- Saves reports as Excel files and compresses them into ZIP archives.
- Sends reports as email attachments to configurable recipients.
- Scheduler with configurable timing to automate monthly report generation.
- Web UI for managing email recipients and scheduler configuration.
- Logs report generation and email sending status.
- REST API endpoints for integration and management.

---

## Technologies Used

- Python 3.12+
- Flask (Web Framework)
- Flask-SQLAlchemy (ORM with SQLite for app data)
- APScheduler (Background scheduling)
- Oracle Database (Data source)
- Pandas (Data processing and Excel export)
- smtplib and email (Email sending)
- SQLite (Local app database)
- HTML/CSS/JS (Frontend templates)

---

## Prerequisites

- Python 3.12 or later
- Oracle Instant Client installed and configured for `oracledb` Python driver
- Access to Oracle DB with credentials
- SMTP email server access (with valid credentials)

---

## Installation


