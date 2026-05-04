import json
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from flask import url_for
from config import SMTP_SERVER, SMTP_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD, SENDER_NAME
from database import get_db

def get_leads_by_segment(conditions_json):
    db = get_db()
    conditions = json.loads(conditions_json) if conditions_json else {}
    query = "SELECT id, name, email, company FROM leads WHERE 1=1"
    params = []
    if 'status' in conditions:
        query += " AND status = ?"
        params.append(conditions['status'])
    if 'min_score' in conditions:
        query += " AND score >= ?"
        params.append(conditions['min_score'])
    if 'services_interest' in conditions:
        query += " AND id IN (SELECT lead_id FROM form_services WHERE service LIKE ?)"  # simplified
        params.append(f"%{conditions['services_interest']}%")
    leads = db.execute(query, params).fetchall()
    return leads

def update_lead_score(lead_id, points):
    db = get_db()
    db.execute('UPDATE leads SET score = score + ? WHERE id = ?', (points, lead_id))
    db.commit()

def track_event(lead_id, campaign_id, event_type, link_url=None):
    db = get_db()
    db.execute('INSERT INTO email_events (lead_id, campaign_id, event_type, link_url) VALUES (?,?,?,?)',
               (lead_id, campaign_id, event_type, link_url))
    db.commit()
    # Add score points for engagement
    if event_type == 'opened':
        update_lead_score(lead_id, 5)
    elif event_type == 'clicked':
        update_lead_score(lead_id, 10)

def create_campaign(name, subject, html_content, segment_filter, scheduled_at=None):
    db = get_db()
    cur = db.execute('''INSERT INTO email_campaigns (name, subject, html_content, segment_filter, scheduled_at, status)
                        VALUES (?,?,?,?,?,?)''',
                     (name, subject, html_content, json.dumps(segment_filter), scheduled_at, 'scheduled' if scheduled_at else 'draft'))
    db.commit()
    return cur.lastrowid

def send_campaign_now(campaign_id):
    db = get_db()
    camp = db.execute('SELECT * FROM email_campaigns WHERE id=?', (campaign_id,)).fetchone()
    if not camp or camp['status'] == 'sent':
        return 0, 0
    leads = get_leads_by_segment(camp['segment_filter'])
    sent_count, fail_count = send_bulk_emails_with_tracking(leads, camp['subject'], camp['html_content'], camp['id'])
    db.execute('UPDATE email_campaigns SET status="sent", sent_at=CURRENT_TIMESTAMP WHERE id=?', (campaign_id,))
    db.commit()
    return sent_count, fail_count

def send_bulk_emails_with_tracking(leads, subject, html_body, campaign_id):
    sent = 0
    failed = 0
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    for lead in leads:
        try:
            # Prepare tracking links
            track_open = url_for('track_open', lead_id=lead['id'], campaign_id=campaign_id, _external=True)
            track_click_base = url_for('track_click', lead_id=lead['id'], campaign_id=campaign_id, url='', _external=True)
            personalized = html_body
            personalized = personalized.replace('{{NAME}}', lead['name'])
            personalized = personalized.replace('{{EMAIL}}', lead['email'])
            personalized = personalized.replace('{{COMPANY}}', lead['company'] or '')
            personalized = personalized.replace('{{TRACK_OPEN}}', f'<img src="{track_open}" width="1" height="1" />')
            # Replace links with tracking: not done here for simplicity; you can implement a regex
            msg = MIMEText(personalized, 'html')
            msg['Subject'] = subject
            msg['From'] = f"{SENDER_NAME} <{EMAIL_ADDRESS}>"
            msg['To'] = lead['email']
            server.send_message(msg)
            # Log sent event
            db = get_db()
            db.execute('INSERT INTO email_events (lead_id, campaign_id, event_type) VALUES (?,?,?)',
                       (lead['id'], campaign_id, 'sent'))
            db.commit()
            sent += 1
        except Exception as e:
            failed += 1
    server.quit()
    return sent, failed

def get_campaign_stats(campaign_id):
    db = get_db()
    sent = db.execute('SELECT COUNT(*) FROM email_events WHERE campaign_id=? AND event_type="sent"', (campaign_id,)).fetchone()[0]
    opened = db.execute('SELECT COUNT(*) FROM email_events WHERE campaign_id=? AND event_type="opened"', (campaign_id,)).fetchone()[0]
    clicked = db.execute('SELECT COUNT(*) FROM email_events WHERE campaign_id=? AND event_type="clicked"', (campaign_id,)).fetchone()[0]
    open_rate = round(opened / sent * 100, 1) if sent else 0
    click_rate = round(clicked / sent * 100, 1) if sent else 0
    return {'sent': sent, 'opened': opened, 'clicked': clicked, 'open_rate': open_rate, 'click_rate': click_rate}