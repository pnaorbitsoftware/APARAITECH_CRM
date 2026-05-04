import sqlite3
import hashlib
from flask import g
from config import DATABASE

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        # Leads table
        cursor.execute('''CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            company TEXT,
            status TEXT DEFAULT 'New',
            score INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Forms table
        cursor.execute('''CREATE TABLE IF NOT EXISTS forms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, email TEXT, phone TEXT, company TEXT, role TEXT,
            services TEXT, requirement TEXT, preferred_time TEXT, heard_from TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Email campaigns table
        cursor.execute('''CREATE TABLE IF NOT EXISTS email_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            subject TEXT,
            html_content TEXT,
            segment_filter TEXT,
            scheduled_at TIMESTAMP,
            sent_at TIMESTAMP,
            status TEXT DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Email events (tracking)
        cursor.execute('''CREATE TABLE IF NOT EXISTS email_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            campaign_id INTEGER,
            event_type TEXT,
            link_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Automation rules
        cursor.execute('''CREATE TABLE IF NOT EXISTS automation_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            trigger_type TEXT,
            trigger_value TEXT,
            action_type TEXT,
            action_value TEXT,
            campaign_id INTEGER,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Segments
        cursor.execute('''CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            conditions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()

def close_db(e=None):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()# ---------- ADD THIS AT THE BOTTOM OF database.py ----------
def init_users():
    conn = sqlite3.connect("crm.db")
    c = conn.cursor()
    # Create users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'employee'
    )''')
    # Insert default admin (admin@aparaitech.com / admin123)
    import hashlib
    hashed = hashlib.sha256('admin123'.encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (email, password, role) VALUES (?,?,?)",
              ('admin@aparaitech.com', hashed, 'admin'))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    init_users()
    app.run(debug=True)