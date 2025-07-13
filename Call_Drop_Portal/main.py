import os
import zipfile
import oracledb
import pandas as pd
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import traceback
from threading import Lock
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///reports.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-here'

db = SQLAlchemy(app)
scheduler = BackgroundScheduler()
scheduler_lock = Lock()

# Oracle DB config



# Database Models
class EmailRecipient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    name = db.Column(db.String(255), nullable=True)
    added_date = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)


class ReportLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(50), nullable=False)  # success, failed, too_large
    file_size_mb = db.Column(db.Float, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    sent_to = db.Column(db.Text, nullable=True)  # JSON string of email addresses


class SchedulerConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_active = db.Column(db.Boolean, default=False)
    run_day = db.Column(db.Integer, default=3)  # 3rd of each month
    run_hour = db.Column(db.Integer, default=9)  # 9 AM
    run_minute = db.Column(db.Integer, default=0)
    last_run = db.Column(db.DateTime, nullable=True)
    next_run = db.Column(db.DateTime, nullable=True)


# Initialize database
with app.app_context():
    db.create_all()
    # Create default scheduler config if not exists
    if not SchedulerConfig.query.first():
        config = SchedulerConfig()
        db.session.add(config)
        db.session.commit()


def get_query(query_type, start_date, end_date):
    """Get SQL query based on type"""
    queries = {
        'off_net': f"""
        SELECT /*+ FULL(p) MATERIALIZE */
            M04_MSISDNAPARTY,
            SUM(CASE WHEN ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) OFF_NET_CALL_DROPS,
            SUM(CASE WHEN Call_Drops = 1 AND ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) AS one_call_drop,
            SUM(CASE WHEN Call_Drops = 2 AND ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) AS two_call_drop,
            SUM(CASE WHEN Call_Drops = 3 AND ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) AS three_call_drop,
            SUM(CASE WHEN Call_Drops = 4 AND ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) AS four_call_drop,
            SUM(CASE WHEN Call_Drops = 5 AND ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) AS five_call_drop,
            SUM(CASE WHEN Call_Drops = 6 AND ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) AS six_call_drop,
            SUM(CASE WHEN Call_Drops = 7 AND ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) AS seven_call_drop,
            SUM(CASE WHEN Call_Drops >= 8 AND ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) AS eight_or_more_call_drop
        FROM (
            SELECT /*+ FULL(p) MATERIALIZE */
                P.M04_MSISDNAPARTY,
                COUNT(P.M01_CALLTYPE) AS Call_Drops,
                CASE
                    WHEN (P.M05_MSISDNBPARTY LIKE '15%' OR P.M05_MSISDNBPARTY LIKE '015%' OR P.M05_MSISDNBPARTY LIKE '88015%') THEN 'ON NET' ELSE 'OFF NET'
                END AS ON_OFF
            FROM l1_msc p
            WHERE
                P.PROCESSED_DATE BETWEEN TO_DATE('{start_date}', 'DD-MM-YYYY') AND TO_DATE('{end_date}', 'DD-MM-YYYY')
                AND P.M01_CALLTYPE IN ('MOC', 'MTC')
                AND P.M11_CAUSEOFTERMINATION IN ('stableCallAbnormalTermination', 'NETWORK FAILURE', 'TRUNK CIRCUIT PROTOCOL ERROR', 'NETWORK, LINE OUT OF SERVICE')
            GROUP BY
                P.M04_MSISDNAPARTY,
                CASE
                    WHEN (P.M05_MSISDNBPARTY LIKE '15%' OR P.M05_MSISDNBPARTY LIKE '015%' OR P.M05_MSISDNBPARTY LIKE '88015%') THEN 'ON NET' ELSE 'OFF NET'
                END
        )
        GROUP BY M04_MSISDNAPARTY
        """,
        'on_net': f"""
        SELECT /*+ FULL(p) MATERIALIZE */
            M04_MSISDNAPARTY,
            SUM(CASE WHEN ON_OFF = 'ON NET' THEN 1 ELSE 0 END) ON_NET_CALL_DROPS,
            SUM(CASE WHEN Call_Drops = 1 AND ON_OFF = 'ON NET' THEN 1 ELSE 0 END) AS one_call_drop,
            SUM(CASE WHEN Call_Drops = 2 AND ON_OFF = 'ON NET' THEN 1 ELSE 0 END) AS two_call_drop,
            SUM(CASE WHEN Call_Drops = 3 AND ON_OFF = 'ON NET' THEN 1 ELSE 0 END) AS three_call_drop,
            SUM(CASE WHEN Call_Drops = 4 AND ON_OFF = 'ON NET' THEN 1 ELSE 0 END) AS four_call_drop,
            SUM(CASE WHEN Call_Drops = 5 AND ON_OFF = 'ON NET' THEN 1 ELSE 0 END) AS five_call_drop,
            SUM(CASE WHEN Call_Drops = 6 AND ON_OFF = 'ON NET' THEN 1 ELSE 0 END) AS six_call_drop,
            SUM(CASE WHEN Call_Drops = 7 AND ON_OFF = 'ON NET' THEN 1 ELSE 0 END) AS seven_call_drop,
            SUM(CASE WHEN Call_Drops >= 8 AND ON_OFF = 'ON NET' THEN 1 ELSE 0 END) AS eight_or_more_call_drop,
            SUM(CASE WHEN ON_OFF = 'ON NET' THEN min_return ELSE 0 END) AS total_min_return
        FROM (
            SELECT /*+ FULL(p) MATERIALIZE */
                P.M04_MSISDNAPARTY,
                COUNT(P.M01_CALLTYPE) AS Call_Drops,
                CASE
                    WHEN COUNT(P.M01_CALLTYPE) <= 2 THEN COUNT(P.M01_CALLTYPE) * 30
                    WHEN COUNT(P.M01_CALLTYPE) > 2 AND COUNT(P.M01_CALLTYPE) <= 7 THEN 60 + (COUNT(P.M01_CALLTYPE) - 2) * 40
                END AS min_return,
                CASE
                    WHEN (P.M05_MSISDNBPARTY LIKE '15%' OR P.M05_MSISDNBPARTY LIKE '015%' OR P.M05_MSISDNBPARTY LIKE '88015%') THEN 'ON NET' ELSE 'OFF NET'
                END AS ON_OFF
            FROM l1_msc p
            WHERE
                P.PROCESSED_DATE BETWEEN TO_DATE('{start_date}', 'DD-MM-YYYY') AND TO_DATE('{end_date}', 'DD-MM-YYYY')
                AND P.M01_CALLTYPE IN ('MOC', 'MTC')
                AND P.M11_CAUSEOFTERMINATION IN ('stableCallAbnormalTermination', 'NETWORK FAILURE', 'TRUNK CIRCUIT PROTOCOL ERROR', 'NETWORK, LINE OUT OF SERVICE')
            GROUP BY
                P.M04_MSISDNAPARTY,
                CASE
                    WHEN (P.M05_MSISDNBPARTY LIKE '15%' OR P.M05_MSISDNBPARTY LIKE '015%' OR P.M05_MSISDNBPARTY LIKE '88015%') THEN 'ON NET' ELSE 'OFF NET'
                END
        )
        GROUP BY M04_MSISDNAPARTY
        """,
        'day_wise': f"""
        SELECT /*+ FULL(p) MATERIALIZE */
            PROCESSED_DATE AS DATE_VALUE,
            COUNT(*) AS No_of_Call_Drops,
            SUM(CASE WHEN ON_OFF = 'ON NET' THEN 1 ELSE 0 END) ON_NET_CALL_DROPS,
            SUM(CASE WHEN ON_OFF = 'OFF NET' THEN 1 ELSE 0 END) OFF_NET_CALL_DROPS
        FROM (
            SELECT /*+ FULL(p) MATERIALIZE */
                P.PROCESSED_DATE,
                P.M04_MSISDNAPARTY,
                COUNT(P.M01_CALLTYPE) AS Call_Drops,
                CASE
                    WHEN COUNT(P.M01_CALLTYPE) <= 2 THEN ROUND((COUNT(P.M01_CALLTYPE) * 30) / 60, 0)
                    WHEN COUNT(P.M01_CALLTYPE) > 2 AND COUNT(P.M01_CALLTYPE) <= 7 THEN ROUND((60 + (COUNT(P.M01_CALLTYPE) - 2) * 40) / 60, 0)
                END AS min_return,
                CASE
                    WHEN (P.M05_MSISDNBPARTY LIKE '15%' OR P.M05_MSISDNBPARTY LIKE '015%' OR P.M05_MSISDNBPARTY LIKE '88015%') THEN 'ON NET' ELSE 'OFF NET'
                END AS ON_OFF
            FROM l1_msc p
            WHERE
                P.PROCESSED_DATE BETWEEN TO_DATE('{start_date}', 'DD-MM-YYYY') AND TO_DATE('{end_date}', 'DD-MM-YYYY')
                AND P.M01_CALLTYPE IN ('MOC', 'MTC')
                AND P.M11_CAUSEOFTERMINATION IN ('stableCallAbnormalTermination', 'NETWORK FAILURE', 'TRUNK CIRCUIT PROTOCOL ERROR', 'NETWORK, LINE OUT OF SERVICE')
            GROUP BY
                P.PROCESSED_DATE, P.M04_MSISDNAPARTY,
                CASE
                    WHEN (P.M05_MSISDNBPARTY LIKE '15%' OR P.M05_MSISDNBPARTY LIKE '015%' OR P.M05_MSISDNBPARTY LIKE '88015%') THEN 'ON NET' ELSE 'OFF NET'
                END
        )
        GROUP BY PROCESSED_DATE
        ORDER BY PROCESSED_DATE
        """
    }
    return queries.get(query_type)


def generate_report(start_date, end_date, report_types=['off_net', 'on_net', 'day_wise']):
    """Generate reports for the specified date range"""
    results = []

    try:
        with oracledb.connect(**DB_CONFIG) as conn:
            logger.info(f"Connected to Oracle DB for report generation")

            period_name = f"{start_date.strftime('%B_%Y')}_to_{end_date.strftime('%B_%Y')}"

            for report_type in report_types:
                try:
                    query = get_query(report_type, start_date.strftime('%d-%m-%Y'), end_date.strftime('%d-%m-%Y'))
                    df = pd.read_sql(query, conn)

                    # Generate filename
                    if report_type == 'off_net':
                        filename = f'customer_wise_off_net_call_drop_report_{period_name}.xlsx'
                        report_name = "Monthly Call Drop Report (Off Net)"
                    elif report_type == 'on_net':
                        filename = f'customer_wise_on_net_call_drop_report_{period_name}.xlsx'
                        report_name = "Monthly Call Drop Report (On Net)"
                    elif report_type == 'day_wise':
                        filename = f'day_wise_call_drop_report_{period_name}.xlsx'
                        report_name = "Day Wise Call Drop Report"

                    # Save Excel file
                    df.to_excel(filename, index=False)

                    # Create zip file
                    zip_name = f"{os.path.splitext(filename)[0]}.zip"
                    with zipfile.ZipFile(zip_name, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
                        zipf.write(filename, arcname=os.path.basename(filename))

                    # Get file size
                    zip_size_mb = os.path.getsize(zip_name) / (1024 * 1024)

                    # Clean up Excel file
                    os.remove(filename)

                    results.append({
                        'type': report_type,
                        'name': report_name,
                        'filename': zip_name,
                        'size_mb': zip_size_mb,
                        'records': len(df)
                    })

                    logger.info(f"Generated {report_type} report: {zip_name} ({zip_size_mb:.2f} MB)")

                except Exception as e:
                    logger.error(f"Error generating {report_type} report: {str(e)}")
                    results.append({
                        'type': report_type,
                        'name': report_name,
                        'error': str(e)
                    })

    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        raise e

    return results


def send_email_report(report_info, recipients, start_date, end_date):
    """Send email with report attachment"""
    try:
        if report_info['size_mb'] > 20:
            # Log as too large
            log_entry = ReportLog(
                report_type=report_info['type'],
                start_date=start_date,
                end_date=end_date,
                status='too_large',
                file_size_mb=report_info['size_mb'],
                error_message=f"File too large: {report_info['size_mb']:.2f} MB"
            )
            db.session.add(log_entry)
            db.session.commit()
            return False, f"File too large: {report_info['size_mb']:.2f} MB"

        period_name = f"{start_date.strftime('%B %Y')} to {end_date.strftime('%B %Y')}"

        msg = EmailMessage()
        msg['Subject'] = f"{report_info['name']} - {period_name}"
        msg['From'] = SMTP_USER
        msg['To'] = ', '.join(recipients)

        # Email body
        body = f"""Dear Sir/Madam,

Please find attached the {report_info['name'].lower()} for the period {period_name}.

Report Details:
- Report Type: {report_info['name']}
- Period: {period_name}
- Total Records: {report_info.get('records', 'N/A')}
- File Size: {report_info['size_mb']:.2f} MB

This report was generated automatically by the Teletalk Call Drop Report System.

Best regards,
Teletalk Network Operations Team
"""

        msg.set_content(body)

        # Attach file
        with open(report_info['filename'], 'rb') as f:
            msg.add_attachment(
                f.read(),
                maintype='application',
                subtype='zip',
                filename=os.path.basename(report_info['filename'])
            )

        # Send email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)

        # Log success
        log_entry = ReportLog(
            report_type=report_info['type'],
            start_date=start_date,
            end_date=end_date,
            status='success',
            file_size_mb=report_info['size_mb'],
            sent_to=json.dumps(recipients)
        )
        db.session.add(log_entry)
        db.session.commit()

        return True, "Email sent successfully"

    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")

        # Log error
        log_entry = ReportLog(
            report_type=report_info['type'],
            start_date=start_date,
            end_date=end_date,
            status='failed',
            error_message=str(e)
        )
        db.session.add(log_entry)
        db.session.commit()

        return False, str(e)


def scheduled_report_job():
    """Job function for scheduled reports"""
    try:
        logger.info("Starting scheduled report generation...")

        # Get previous month dates
        today = datetime.today()
        first_day_this_month = today.replace(day=1)
        last_day_prev_month = first_day_this_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)

        # Get active recipients
        recipients = [r.email for r in EmailRecipient.query.filter_by(is_active=True).all()]

        if not recipients:
            logger.warning("No active recipients found for scheduled report")
            return

        # Generate reports
        reports = generate_report(first_day_prev_month, last_day_prev_month)

        # Send emails
        for report in reports:
            if 'error' not in report:
                success, message = send_email_report(report, recipients, first_day_prev_month, last_day_prev_month)
                logger.info(f"Report {report['type']}: {message}")

                # Clean up file
                if os.path.exists(report['filename']):
                    os.remove(report['filename'])

        # Update last run
        config = SchedulerConfig.query.first()
        config.last_run = datetime.now()
        db.session.commit()

        logger.info("Scheduled report generation completed")

    except Exception as e:
        logger.error(f"Error in scheduled report job: {str(e)}")
        logger.error(traceback.format_exc())


# Routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/emails', methods=['GET'])
def get_emails():
    emails = EmailRecipient.query.all()
    return jsonify([{
        'id': e.id,
        'email': e.email,
        'name': e.name,
        'added_date': e.added_date.isoformat(),
        'is_active': e.is_active
    } for e in emails])


@app.route('/api/emails', methods=['POST'])
def add_email():
    data = request.get_json()

    # Check if email already exists
    existing = EmailRecipient.query.filter_by(email=data['email']).first()
    if existing:
        return jsonify({'error': 'Email already exists'}), 400

    email = EmailRecipient(
        email=data['email'],
        name=data.get('name', ''),
        is_active=True
    )

    db.session.add(email)
    db.session.commit()

    return jsonify({'message': 'Email added successfully'})


@app.route('/api/emails/<int:email_id>', methods=['DELETE'])
def delete_email(email_id):
    email = EmailRecipient.query.get_or_404(email_id)
    db.session.delete(email)
    db.session.commit()
    return jsonify({'message': 'Email deleted successfully'})


@app.route('/api/emails/<int:email_id>/toggle', methods=['POST'])
def toggle_email(email_id):
    email = EmailRecipient.query.get_or_404(email_id)
    email.is_active = not email.is_active
    db.session.commit()
    return jsonify({'message': 'Email status updated'})


@app.route('/api/scheduler', methods=['GET'])
def get_scheduler_status():
    config = SchedulerConfig.query.first()
    return jsonify({
        'is_active': config.is_active,
        'run_day': config.run_day,
        'run_hour': config.run_hour,
        'run_minute': config.run_minute,
        'last_run': config.last_run.isoformat() if config.last_run else None,
        'next_run': config.next_run.isoformat() if config.next_run else None
    })


@app.route('/api/scheduler/start', methods=['POST'])
def start_scheduler():
    try:
        with scheduler_lock:
            config = SchedulerConfig.query.first()

            # Remove existing job if any
            if scheduler.get_job('monthly_report'):
                scheduler.remove_job('monthly_report')

            # Add new job
            trigger = CronTrigger(
                day=config.run_day,
                hour=config.run_hour,
                minute=config.run_minute
            )

            scheduler.add_job(
                func=scheduled_report_job,
                trigger=trigger,
                id='monthly_report',
                name='Monthly Report Generation',
                replace_existing=True
            )

            if not scheduler.running:
                scheduler.start()

            config.is_active = True
            config.next_run = scheduler.get_job('monthly_report').next_run_time
            db.session.commit()

            return jsonify({'message': 'Scheduler started successfully'})

    except Exception as e:
        logger.error(f"Error starting scheduler: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/scheduler/stop', methods=['POST'])
def stop_scheduler():
    try:
        with scheduler_lock:
            if scheduler.get_job('monthly_report'):
                scheduler.remove_job('monthly_report')

            config = SchedulerConfig.query.first()
            config.is_active = False
            config.next_run = None
            db.session.commit()

            return jsonify({'message': 'Scheduler stopped successfully'})

    except Exception as e:
        logger.error(f"Error stopping scheduler: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/scheduler/config', methods=['POST'])
def update_scheduler_config():
    data = request.get_json()
    config = SchedulerConfig.query.first()

    config.run_day = data.get('run_day', config.run_day)
    config.run_hour = data.get('run_hour', config.run_hour)
    config.run_minute = data.get('run_minute', config.run_minute)

    db.session.commit()

    # If scheduler is active, restart it with new config
    if config.is_active:
        start_scheduler()

    return jsonify({'message': 'Scheduler configuration updated'})


@app.route('/api/reports/generate', methods=['POST'])
def generate_manual_report():
    try:
        data = request.get_json()

        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d')
        report_types = data.get('report_types', ['off_net', 'on_net', 'day_wise'])

        # Generate reports
        reports = generate_report(start_date, end_date, report_types)

        # Get recipients
        recipients = [r.email for r in EmailRecipient.query.filter_by(is_active=True).all()]

        if not recipients:
            return jsonify({'error': 'No active recipients found'}), 400

        results = []
        for report in reports:
            if 'error' not in report:
                success, message = send_email_report(report, recipients, start_date, end_date)
                results.append({
                    'type': report['type'],
                    'success': success,
                    'message': message,
                    'size_mb': report['size_mb']
                })

                # Clean up file
                if os.path.exists(report['filename']):
                    os.remove(report['filename'])
            else:
                results.append({
                    'type': report['type'],
                    'success': False,
                    'message': report['error']
                })

        return jsonify({
            'message': 'Report generation completed',
            'results': results
        })

    except Exception as e:
        logger.error(f"Error in manual report generation: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports/logs', methods=['GET'])
def get_report_logs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    logs = ReportLog.query.order_by(ReportLog.created_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'logs': [{
            'id': log.id,
            'report_type': log.report_type,
            'start_date': log.start_date.isoformat(),
            'end_date': log.end_date.isoformat(),
            'status': log.status,
            'file_size_mb': log.file_size_mb,
            'error_message': log.error_message,
            'created_date': log.created_date.isoformat(),
            'sent_to': json.loads(log.sent_to) if log.sent_to else []
        } for log in logs.items],
        'has_next': logs.has_next,
        'has_prev': logs.has_prev,
        'page': page,
        'pages': logs.pages,
        'total': logs.total
    })


if __name__ == '__main__':
    # Initialize scheduler
    scheduler.start()

    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()