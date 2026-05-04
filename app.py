from flask import Flask, render_template, request, redirect, url_for, flash, send_file, g, jsonify
import sqlite3, csv, json
from io import StringIO
from datetime import datetime, timedelta
from config import SECRET_KEY
from database import get_db, init_db
from marketing import (get_leads_by_segment, update_lead_score, track_event,
                       create_campaign, send_campaign_now, get_campaign_stats,
                       send_bulk_emails_with_tracking)

app = Flask(__name__)
app.secret_key = SECRET_KEY

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ----------------- Core Routes (same as before, but with score updates) -----------------
@app.route('/')
def dashboard():
    db = get_db()
    total_leads = db.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
    new_leads = db.execute("SELECT COUNT(*) FROM leads WHERE status='New'").fetchone()[0]
    converted = db.execute("SELECT COUNT(*) FROM leads WHERE status='Converted'").fetchone()[0]
    total_forms = db.execute('SELECT COUNT(*) FROM forms').fetchone()[0]
    return render_template('dashboard.html', total_leads=total_leads, new_leads=new_leads,
                           converted=converted, total_forms=total_forms)

@app.route('/leads')
def leads():
    status_filter = request.args.get('status', '')
    db = get_db()
    if status_filter:
        leads = db.execute('SELECT * FROM leads WHERE status=? ORDER BY created_at DESC', (status_filter,)).fetchall()
    else:
        leads = db.execute('SELECT * FROM leads ORDER BY created_at DESC').fetchall()
    return render_template('leads.html', leads=leads, filter_status=status_filter)

@app.route('/lead/add', methods=['POST'])
def add_lead():
    name = request.form['name']
    email = request.form['email']
    phone = request.form.get('phone', '')
    company = request.form.get('company', '')
    status = request.form.get('status', 'New')
    db = get_db()
    try:
        db.execute('INSERT INTO leads (name, email, phone, company, status) VALUES (?,?,?,?,?)',
                   (name, email, phone, company, status))
        db.commit()
        flash('Lead added successfully', 'success')
    except sqlite3.IntegrityError:
        flash('Email already exists', 'danger')
    return redirect(url_for('leads'))

@app.route('/lead/edit/<int:lead_id>', methods=['POST'])
def edit_lead(lead_id):
    name = request.form['name']
    email = request.form['email']
    phone = request.form.get('phone', '')
    company = request.form.get('company', '')
    status = request.form['status']
    db = get_db()
    try:
        db.execute('UPDATE leads SET name=?, email=?, phone=?, company=?, status=? WHERE id=?',
                   (name, email, phone, company, status, lead_id))
        db.commit()
        flash('Lead updated', 'success')
    except sqlite3.IntegrityError:
        flash('Email already exists', 'danger')
    return redirect(url_for('leads'))

@app.route('/lead/delete/<int:lead_id>')
def delete_lead(lead_id):
    db = get_db()
    db.execute('DELETE FROM leads WHERE id=?', (lead_id,))
    db.commit()
    flash('Lead deleted', 'success')
    return redirect(url_for('leads'))

@app.route('/import-csv', methods=['POST'])
def import_csv():
    file = request.files['csv']
    if not file:
        flash('No file uploaded', 'danger')
        return redirect(url_for('leads'))
    content = file.read().decode('utf-8')
    reader = csv.DictReader(StringIO(content))
    db = get_db()
    success = 0
    for row in reader:
        email = row.get('email') or row.get('Email')
        name = row.get('name') or row.get('Name')
        if email and '@' in email and name:
            try:
                db.execute('INSERT INTO leads (name, email) VALUES (?,?)', (name, email))
                success += 1
            except: pass
    db.commit()
    flash(f'Imported {success} leads', 'success')
    return redirect(url_for('leads'))

@app.route('/export-leads')
def export_leads():
    import csv
    from io import StringIO, BytesIO
    db = get_db()
    leads = db.execute('SELECT name, email, phone, company, status, score, created_at FROM leads').fetchall()
    
    # Step 1: write CSV to a text buffer (StringIO)
    text_buffer = StringIO()
    writer = csv.writer(text_buffer)
    writer.writerow(['Name', 'Email', 'Phone', 'Company', 'Status', 'Score', 'Created At'])
    for lead in leads:
        writer.writerow([
            lead['name'],
            lead['email'],
            lead['phone'] or '',
            lead['company'] or '',
            lead['status'],
            lead['score'] or 0,
            lead['created_at']
        ])
    
    # Step 2: convert the text buffer to bytes (BytesIO) for send_file
    binary_buffer = BytesIO()
    binary_buffer.write(text_buffer.getvalue().encode('utf-8'))
    binary_buffer.seek(0)
    
    return send_file(binary_buffer, as_attachment=True, download_name='leads_export.csv', mimetype='text/csv')

# ----------------- Email Campaign (basic) -----------------
@app.route('/email', methods=['GET', 'POST'])
def email_campaign():
    db = get_db()
    if request.method == 'POST':
        lead_ids = request.form.getlist('lead_ids')
        subject = request.form['subject']
        html_body = request.form['html_body']
        if not lead_ids:
            flash('No leads selected', 'warning')
            return redirect(url_for('email_campaign'))
        leads = db.execute(f'SELECT * FROM leads WHERE id IN ({",".join(["?"]*len(lead_ids))})', lead_ids).fetchall()
        sent, failed = send_bulk_emails_with_tracking(leads, subject, html_body, campaign_id=0)  # optional campaign id
        flash(f'Emails sent: {sent}, failed: {failed}', 'info')
        return redirect(url_for('leads'))
    leads = db.execute('SELECT id, name, email FROM leads ORDER BY created_at DESC').fetchall()
    return render_template('email_campaign.html', leads=leads)

# ----------------- Forms -----------------
@app.route('/forms', methods=['GET', 'POST'])
def form_submissions():
    db = get_db()
    if request.method == 'POST':
        db.execute('''INSERT INTO forms (name, email, phone, company, role, services, requirement, preferred_time, heard_from)
                      VALUES (?,?,?,?,?,?,?,?,?)''',
                   (request.form['name'], request.form['email'], request.form.get('phone',''),
                    request.form.get('company',''), request.form.get('role',''),
                    request.form.get('services',''), request.form.get('requirement',''),
                    request.form.get('preferred_time',''), request.form.get('heard_from','')))
        db.commit()
        flash('Form submission saved', 'success')
        return redirect(url_for('form_submissions'))
    submissions = db.execute('SELECT * FROM forms ORDER BY submitted_at DESC').fetchall()
    return render_template('forms.html', submissions=submissions)

# ----------------- ADVANCED MARKETING ROUTES -----------------
@app.route('/marketing-dashboard')
def advanced_dashboard():
    db = get_db()
    total_leads = db.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
    new_leads = db.execute("SELECT COUNT(*) FROM leads WHERE status='New'").fetchone()[0]
    engaged_leads = db.execute('SELECT COUNT(DISTINCT lead_id) FROM email_events WHERE event_type="opened"').fetchone()[0] or 0
    converted = db.execute("SELECT COUNT(*) FROM leads WHERE status='Converted'").fetchone()[0]
    total_forms = db.execute('SELECT COUNT(*) FROM forms').fetchone()[0]
    sent_total = db.execute('SELECT COUNT(*) FROM email_events WHERE event_type="sent"').fetchone()[0]
    opened_total = db.execute('SELECT COUNT(*) FROM email_events WHERE event_type="opened"').fetchone()[0]
    opened_rate = round((opened_total / sent_total * 100), 1) if sent_total else 0
    conversion_rate = round((converted / total_leads * 100), 1) if total_leads else 0

    # Score distribution
    score_buckets = [[0,20,'0-20'],[21,40,'21-40'],[41,60,'41-60'],[61,80,'61-80'],[81,100,'81-100']]
    score_distribution = []
    for low, high, label in score_buckets:
        cnt = db.execute('SELECT COUNT(*) FROM leads WHERE score BETWEEN ? AND ?', (low, high)).fetchone()[0]
        score_distribution.append({'range': label, 'count': cnt})

    # Trend last 7 days
    today = datetime.now().date()
    trend_dates = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6, -1, -1)]
    trend_opens, trend_clicks = [], []
    for d in trend_dates:
        opens = db.execute('SELECT COUNT(*) FROM email_events WHERE event_type="opened" AND DATE(created_at)=?', (d,)).fetchone()[0]
        clicks = db.execute('SELECT COUNT(*) FROM email_events WHERE event_type="clicked" AND DATE(created_at)=?', (d,)).fetchone()[0]
        trend_opens.append(opens)
        trend_clicks.append(clicks)

    # Recent campaigns
    campaigns = db.execute('SELECT id, name FROM email_campaigns ORDER BY created_at DESC LIMIT 5').fetchall()
    camp_list = []
    for c in campaigns:
        stats = get_campaign_stats(c['id'])
        camp_list.append({'name': c['name'], 'sent': stats['sent'], 'opened': stats['opened'],
                          'clicked': stats['clicked'], 'open_rate': stats['open_rate'],
                          'click_rate': stats['click_rate']})

    # Recent forms
    recent_forms = db.execute('SELECT name, services, submitted_at FROM forms ORDER BY submitted_at DESC LIMIT 5').fetchall()

    # Recent activity
    activity = db.execute('''SELECT e.event_type, e.created_at, l.name as lead_name,
                             CASE e.event_type WHEN 'opened' THEN 'opened an email'
                                               WHEN 'clicked' THEN 'clicked a link'
                                               ELSE 'updated' END as message
                             FROM email_events e JOIN leads l ON e.lead_id=l.id
                             ORDER BY e.created_at DESC LIMIT 10''').fetchall()
    recent_activity = []
    for act in activity:
        time_ago = (datetime.now() - datetime.strptime(act['created_at'], '%Y-%m-%d %H:%M:%S')).seconds // 60
        time_ago_str = f"{time_ago} minutes ago" if time_ago < 60 else f"{time_ago//60} hours ago"
        recent_activity.append({'lead_name': act['lead_name'], 'type': act['event_type'],
                                'message': act['message'], 'time_ago': time_ago_str})

    return render_template('marketing_dashboard.html',
                           total_leads=total_leads, new_leads=new_leads,
                           engaged_leads=engaged_leads, converted=converted,
                           total_forms=total_forms, opened_rate=opened_rate,
                           conversion_rate=conversion_rate, score_distribution=score_distribution,
                           trend_dates=trend_dates, trend_opens=trend_opens, trend_clicks=trend_clicks,
                           campaigns=camp_list, recent_forms=recent_forms, recent_activity=recent_activity)

@app.route('/campaigns')
def campaigns():
    db = get_db()
    campaigns = db.execute('SELECT * FROM email_campaigns ORDER BY created_at DESC').fetchall()
    return render_template('campaigns.html', campaigns=campaigns)

@app.route('/campaign/new', methods=['GET', 'POST'])
def new_campaign():
    if request.method == 'POST':
        name = request.form['name']
        subject = request.form['subject']
        html = request.form['html_body']
        conditions = {'status': request.form.get('status'), 'min_score': request.form.get('min_score')}
        conditions = {k:v for k,v in conditions.items() if v}
        create_campaign(name, subject, html, conditions, scheduled_at=None)
        flash('Campaign created', 'success')
        return redirect(url_for('campaigns'))
    return render_template('campaign_form.html')

@app.route('/campaign/send/<int:campaign_id>')
def campaign_send(campaign_id):
    sent, failed = send_campaign_now(campaign_id)
    flash(f'Campaign sent: {sent} delivered, {failed} failed', 'info')
    return redirect(url_for('campaigns'))

@app.route('/campaign/stats/<int:campaign_id>')
def campaign_stats_route(campaign_id):
    stats = get_campaign_stats(campaign_id)
    db = get_db()
    events = db.execute('''SELECT e.event_type, e.created_at, l.name
                           FROM email_events e JOIN leads l ON e.lead_id=l.id
                           WHERE e.campaign_id=? ORDER BY e.created_at DESC''', (campaign_id,)).fetchall()
    return render_template('campaign_report.html', stats=stats, events=events)

@app.route('/track/open/<int:lead_id>/<int:campaign_id>')
def track_open(lead_id, campaign_id):
    track_event(lead_id, campaign_id, 'opened')
    return send_file('static/pixel.png', mimetype='image/png')

@app.route('/track/click/<int:lead_id>/<int:campaign_id>/<path:url>')
def track_click(lead_id, campaign_id, url):
    track_event(lead_id, campaign_id, 'clicked', url)
    return redirect(url)

@app.route('/segments')
def segments():
    db = get_db()
    segs = db.execute('SELECT * FROM segments').fetchall()
    return render_template('segments.html', segments=segs)

@app.route('/segment/create', methods=['POST'])
def create_segment():
    name = request.form['name']
    conditions = {'status': request.form.get('status'), 'min_score': request.form.get('min_score')}
    conditions = {k:v for k,v in conditions.items() if v}
    db = get_db()
    db.execute('INSERT INTO segments (name, conditions) VALUES (?,?)', (name, json.dumps(conditions)))
    db.commit()
    flash('Segment created', 'success')
    return redirect(url_for('segments'))

@app.route('/lead-scoring')
def lead_scoring():
    db = get_db()
    leads = db.execute('SELECT name, email, score FROM leads ORDER BY score DESC').fetchall()
    return render_template('lead_scoring.html', leads=leads)

@app.route('/email-automation')
def automation():
    db = get_db()
    rules = db.execute('SELECT * FROM automation_rules').fetchall()
    return render_template('automation.html', rules=rules)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
    
from flask import session, redirect, url_for, request, flash
from functools import wraps
import hashlib
from database import get_db

def get_user(email):
    db = get_db()
    return db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Admin required', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        pwd = request.form['password']
        hashed = hashlib.sha256(pwd.encode()).hexdigest()
        user = get_user(email)
        if user and user['password'] == hashed:
            session['user_id'] = user['id']
            session['role'] = user['role']
            flash('Logged in', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out', 'info')
    return redirect(url_for('login'))    


