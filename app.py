from flask import Flask, request, redirect, url_for, render_template_string, flash, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime
import sqlite3
import csv
import io
from pathlib import Path

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "stock.db"

secret_file = BASE_DIR / ".flask_secret"
if secret_file.exists():
    app.secret_key = secret_file.read_text(encoding="utf-8").strip()
else:
    app.secret_key = "fallback-secret-key-12345"

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
)

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
                price REAL NOT NULL CHECK(price >= 0),
                cost_price REAL NOT NULL DEFAULT 0 CHECK(cost_price >= 0),
                username TEXT NOT NULL DEFAULT 'RIXX',
                UNIQUE(username, item_id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                unit_cost REAL NOT NULL DEFAULT 0,
                cost_tracked INTEGER NOT NULL DEFAULT 1,
                username TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount >= 0),
                category TEXT NOT NULL,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        user_columns = {
            row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()
        }
        if "role" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'staff'")
        if "is_active" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

        prod_columns = {
            row[1] for row in db.execute("PRAGMA table_info(products)").fetchall()
        }
        if "username" not in prod_columns:
            db.execute("ALTER TABLE products ADD COLUMN username TEXT NOT NULL DEFAULT 'RIXX'")

        tx_columns = {
            row[1] for row in db.execute("PRAGMA table_info(transactions)").fetchall()
        }
        if "username" not in tx_columns:
            db.execute("ALTER TABLE transactions ADD COLUMN username TEXT")

        db.execute(
            "UPDATE users SET role = 'admin', is_active = 1 WHERE username = ?",
            ("RIXX",)
        )

PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shop Stock Manager - {{ role|upper }} Workspace</title>
<style>
*{box-sizing:border-box}
body{font-family:Arial,sans-serif;background:#f3f6fa;color:#202938;margin:0}
header{background:#17365d;color:white;padding:24px}
header h1{margin:0 0 7px}
header p{margin:0;color:#dce8f7}
main{max-width:1100px;margin:24px auto;padding:0 16px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.card,section{background:white;border-radius:12px;padding:20px;margin-bottom:18px;box-shadow:0 2px 8px #0000000a}
.metric{font-size:25px;font-weight:bold;margin-top:10px}
h2{font-size:19px;margin-top:0}
.forms{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px}
label{display:block;font-size:14px;margin:12px 0 5px}
input,select,button{font:inherit;padding:10px;border-radius:6px}
input,select{width:100%;border:1px solid #cbd5e1}
button{background:#1d5da8;color:white;border:0;cursor:pointer;margin-top:12px}
button:hover{background:#16477f}
table{border-collapse:collapse;width:100%;background:white}
th,td{text-align:left;padding:12px 9px;border-bottom:1px solid #e4e9f0}
th{background:#f7f9fc}
.tablewrap{overflow-x:auto}
.notice{padding:12px;background:#e6f5e9;border-radius:7px;margin-bottom:12px}
.error{background:#ffeded}
.small{color:#687588;font-size:13px}
.inline{display:inline}
.inline button{margin:0 3px 3px 0}
a{color:#1759a6}
@media(max-width:600px){header{padding:18px}th,td{font-size:13px;padding:8px 5px}}
</style>
</head>
<body>

<header style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
    <div>
        <h1>Shop Stock Manager</h1>
        <p>Logged in as: <strong>{{ session.get('username', '') }}</strong> ({{ session.get('role', '')|upper }})</p>
    </div>
    <div>
        {% if session.get('role') == 'admin' %}
            <a href="{{ url_for('admin_monitor') }}" style="color:#ffd700;margin-right:15px;font-weight:bold;">Admin Monitor</a>
        {% endif %}
        <form method="post" action="{{ url_for('logout') }}" style="display:inline;">
            <button type="submit" style="background:#dc3545;margin-top:0">Log out</button>
        </form>
    </div>
</header>
<main>
{% for category,message in get_flashed_messages(with_categories=true) %}
<div class="notice {{ 'error' if category == 'error' else '' }}">{{ message }}</div>
{% endfor %}

<div class="cards">
<section>
<h2>Sales, Profit &amp; Expenses {% if session.get('role') != 'admin' %}(Your Performance){% endif %}</h2>
<div class="cards">
    <div class="card">
        Sales revenue
        <div class="metric">{{ "%.2f"|format(sales_revenue) }}</div>
    </div>
    <div class="card">
        Cost of goods sold
        <div class="metric">{{ "%.2f"|format(tracked_cost) }}</div>
    </div>
    <div class="card">
        Total expenses
        <div class="metric" style="color:#d9534f">{{ "%.2f"|format(total_expenses) }}</div>
    </div>
    <div class="card">
        Net profit
        <div class="metric" style="color:#28a745">{{ "%.2f"|format(net_profit) }}</div>
    </div>
</div>
</section>

<div class="forms">
<section>
<h2>Add a product</h2>
<form method="post" action="{{ url_for('add_product') }}">
<label>Product ID</label>
<input name="item_id" required maxlength="50" placeholder="e.g. P001">
<label>Product name</label>
<input name="name" required maxlength="100" placeholder="e.g. Sugar">
<label>Opening quantity</label>
<input name="quantity" type="number" min="0" max="2147483647" required value="0">
<label>Purchase cost per item</label>
<input name="cost_price" type="number" min="0" step="0.01" required>
<label>Price per item</label>
<input name="price" type="number" min="0" step="0.01" required>
<button type="submit">Add product</button>
</form>
</section>

<section>
<h2>Record a sale</h2>
<form method="post" action="{{ url_for('sell') }}">
<label>Product</label>
<select name="item_id" required style="width:100%;padding:10px">
{% for p in products %}
<option value="{{ p.item_id }}">{{ p.item_id }}  {{ p.name }} ({{ p.quantity }} available) {% if session.get('role') == 'admin' %}[Staff: {{ p.username }}]{% endif %}</option>
{% endfor %}
</select>
<label>Quantity sold</label>
<input name="quantity" type="number" min="1" max="2147483647" required>
<button type="submit">Record sale</button>
</form>
</section>

<section>
<h2>Restock a product</h2>
<form method="post" action="{{ url_for('restock') }}">
<label>Product</label>
<select name="item_id" required style="width:100%;padding:10px">
{% for p in products %}
<option value="{{ p.item_id }}">{{ p.item_id }}  {{ p.name }} ({{ p.quantity }} in stock) {% if session.get('role') == 'admin' %}[Staff: {{ p.username }}]{% endif %}</option>
{% endfor %}
</select>
<label>Quantity to add</label>
<input name="quantity" type="number" min="1" max="2147483647" required>
<button type="submit">Add stock</button>
</form>
</section>

<section>
<h2>Record an Expense</h2>
<form method="post" action="{{ url_for('add_expense') }}">
<label>Expense Date</label>
<input name="expense_date" type="date" required value="{{ today_date }}">
<label>Expense Title / Description</label>
<input name="title" required maxlength="100" placeholder="e.g. Transport / Delivery">
<label>Amount</label>
<input name="amount" type="number" min="0" step="0.01" required placeholder="0.00">
<label>Category</label>
<select name="category" required>
<option value="Transport">Transport</option>
<option value="Utilities">Utilities (Electricity/Water)</option>
<option value="Supplies">Shop Supplies</option>
<option value="Maintenance">Maintenance &amp; Repairs</option>
<option value="Other">Other</option>
</select>
<button type="submit" style="background:#d9534f">Record Expense</button>
</form>
</section>
</div>

<section>
<h2>Inventory {% if session.get('role') == 'admin' %}(Combined All Staff Stock){% endif %}</h2>
<p><a href="{{ url_for('daily_report') }}">View Daily Stock Report</a>
{% if session.get("role") == "admin" %} | <a href="{{ url_for('manage_staff') }}">Manage Staff Accounts</a>{% endif %}</p>

<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px">
<form method="get" action="/" style="display:flex;gap:8px;flex:1;min-width:220px">
<input name="q" value="{{ q }}" placeholder="Search by ID or product name">
<button type="submit">Search</button>
</form>
<a href="{{ url_for('export_products') }}" download
   style="display:inline-block;background:#198754;color:white;padding:10px 14px;border-radius:6px;text-decoration:none;font-weight:bold">
Export Inventory CSV
</a>
</div>
<div class="tablewrap">
<table>
<thead><tr><th>ID</th><th>Product</th><th>Quantity</th><th>Price</th><th>Stock value</th>{% if session.get('role') == 'admin' %}<th>Staff Owner</th>{% endif %}<th>Action</th></tr></thead>
<tbody>
{% for p in shown_products %}
<tr>
<td>{{ p.item_id }}</td><td>{{ p.name }}</td><td>{{ p.quantity }}</td>
<td>{{ "%.2f"|format(p.price) }}</td>
<td>{{ "%.2f"|format(p.quantity * p.price) }}</td>
{% if session.get('role') == 'admin' %}<td><strong>{{ p.username }}</strong></td>{% endif %}
<td>
<form class="inline" method="post" action="{{ url_for('delete_product', item_id=p.item_id) }}{% if session.get('role') == 'admin' %}?owner={{ p.username }}{% endif %}" onsubmit="return confirm('Delete this product and its inventory record?')">
<button type="submit">Delete</button>
</form>
</td>
</tr>
{% else %}
<tr><td colspan="{% if session.get('role') == 'admin' %}7{% else %}6{% endif %}">No products found. Add your first product above.</td></tr>
{% endfor %}
</tbody>
</table>
</div>
</section>
</main>
</body>
</html>
"""


@app.before_request
def require_login():
    allowed_endpoints = {"setup", "login", "static"}
    if request.endpoint in allowed_endpoints:
        return None

    with connect_db() as db:
        user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    if user_count == 0:
        return redirect(url_for("setup"))

    if "user_id" not in session:
        return redirect(url_for("login"))

    with connect_db() as db:
        user = db.execute(
            "SELECT id, username, role, is_active FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()

    if user is None or not user["is_active"]:
        session.clear()
        flash("This account is disabled or no longer exists.", "error")
        return redirect(url_for("login"))

    session["username"] = user["username"]
    session["role"] = user["role"]
    return None


@app.route("/setup", methods=["GET", "POST"])
def setup():
    with connect_db() as db:
        user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count > 0:
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
        elif len(password) < 4:
            flash("Password must be at least 4 digits/characters.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            try:
                with connect_db() as db:
                    db.execute(
                        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, 'admin', 1)",
                        (username, generate_password_hash(password))
                    )
                flash("Admin created successfully. Please log in.")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Username already exists.", "error")

    return render_template_string("""
        <!doctype html>
        <html lang="en">
        <head><title>Setup Admin</title></head>
        <body style="font-family:Arial;padding:40px;background:#f3f6fa">
            <main style="max-width:400px;margin:auto;background:white;padding:24px;border-radius:12px">
                <h2>Administrator Setup</h2>
                {% for c, m in get_flashed_messages(with_categories=true) %}<p style="color:red">{{ m }}</p>{% endfor %}
                <form method="post">
                    <label>Username</label><input name="username" required style="width:100%;padding:8px;margin:6px 0">
                    <label>Password (min 4 digits)</label><input type="password" name="password" required style="width:100%;padding:8px;margin:6px 0">
                    <label>Confirm Password</label><input type="password" name="confirm_password" required style="width:100%;padding:8px;margin:6px 0">
                    <button type="submit" style="width:100%;padding:10px;background:#1d5da8;color:white;border:0;border-radius:6px;margin-top:10px">Create Admin</button>
                </form>
            </main>
        </body></html>
    """)


@app.route("/login", methods=["GET", "POST"])
def login():
    with connect_db() as db:
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            return redirect(url_for("setup"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with connect_db() as db:
            user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user and user["is_active"] and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("index"))

        flash("Incorrect username or password, or account is disabled.", "error")

    return render_template_string("""
        <!doctype html>
        <html lang="en">
        <head><title>Login</title></head>
        <body style="font-family:Arial;padding:40px;background:#f3f6fa">
            <main style="max-width:400px;margin:auto;background:white;padding:24px;border-radius:12px">
                <h2>Shop Stock Manager - Login</h2>
                {% for c, m in get_flashed_messages(with_categories=true) %}<p style="color:red">{{ m }}</p>{% endfor %}
                <form method="post">
                    <label>Username</label><input name="username" required style="width:100%;padding:8px;margin:6px 0">
                    <label>Password</label><input type="password" name="password" required style="width:100%;padding:8px;margin:6px 0">
                    <button type="submit" style="width:100%;padding:10px;background:#1d5da8;color:white;border:0;border-radius:6px;margin-top:10px">Log in</button>
                </form>
            </main>
        </body></html>
    """)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/monitor")
def admin_monitor():
    if session.get("role") != "admin":
        flash("Unauthorized access.", "error")
        return redirect(url_for("index"))

    selected_staff = request.args.get("staff", "").strip()
    filter_date = request.args.get("date", "").strip()

    with connect_db() as db:
        all_users = db.execute("SELECT id, username, role, is_active, created_at FROM users ORDER BY id").fetchall()
        
        staff_performance = db.execute("""
            SELECT 
                COALESCE(u.username, t.username, 'RIXX') AS staff_name,
                COALESCE(SUM(CASE WHEN t.action = 'Sale' THEN t.quantity * t.unit_price ELSE 0 END), 0) AS revenue,
                COALESCE(SUM(CASE WHEN t.action = 'Sale' AND t.cost_tracked = 1 THEN t.quantity * t.unit_cost ELSE 0 END), 0) AS tracked_cost,
                COALESCE(SUM(CASE WHEN t.action = 'Sale' AND t.cost_tracked = 1 THEN t.quantity * (t.unit_price - t.unit_cost) ELSE 0 END), 0) AS gross_profit,
                COALESCE(SUM(CASE WHEN t.action = 'Sale' THEN t.quantity ELSE 0 END), 0) AS units_sold,
                COUNT(t.id) AS total_actions
            FROM users u
            LEFT JOIN transactions t ON u.username = t.username
            GROUP BY u.username
            UNION
            SELECT 
                'RIXX' AS staff_name,
                COALESCE(SUM(CASE WHEN action = 'Sale' THEN quantity * unit_price ELSE 0 END), 0) AS revenue,
                COALESCE(SUM(CASE WHEN action = 'Sale' AND cost_tracked = 1 THEN quantity * unit_cost ELSE 0 END), 0) AS tracked_cost,
                COALESCE(SUM(CASE WHEN action = 'Sale' AND cost_tracked = 1 THEN quantity * (unit_price - unit_cost) ELSE 0 END), 0) AS gross_profit,
                COALESCE(SUM(CASE WHEN action = 'Sale' THEN quantity ELSE 0 END), 0) AS units_sold,
                COUNT(id) AS total_actions
            FROM transactions
            WHERE username IS NULL OR username = '' OR username = 'RIXX'
        """).fetchall()

        staff_expenses_summary = db.execute("""
            SELECT username, COALESCE(SUM(amount), 0) AS total_spent, COUNT(id) AS expense_count
            FROM expenses
            GROUP BY username
        """).fetchall()

        expenses_all = db.execute("SELECT * FROM expenses ORDER BY id DESC").fetchall()
        filtered_expenses = [
            ex for ex in expenses_all
            if (not selected_staff or ex["username"] == selected_staff) and
               (not filter_date or ex["created_at"].startswith(filter_date))
        ][:50]

        tx_all = db.execute("SELECT * FROM transactions ORDER BY id DESC").fetchall()
        filtered_transactions = [
            t for t in tx_all
            if (not selected_staff or (t["username"] or "RIXX") == selected_staff) and
               (not filter_date or t["created_at"].startswith(filter_date))
        ][:100]

    return render_template_string("""
        <!doctype html>
        <html lang="en">
        <head>
            <title>Admin Monitoring Dashboard</title>
            <style>
                body{font-family:Arial;background:#f3f6fa;margin:0;padding:24px;color:#202938}
                .container{max-width:1100px;margin:auto;background:white;padding:24px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.05)}
                table{width:100%;border-collapse:collapse;margin-top:15px;margin-bottom:25px}
                th,td{padding:10px;border-bottom:1px solid #ddd;text-align:left}
                th{background:#343a40;color:white}
                .btn{display:inline-block;padding:8px 14px;background:#1d5da8;color:white;text-decoration:none;border-radius:6px}
                .filters{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;margin:20px 0;background:#f7f9fc;padding:15px;border-radius:8px}
                .filters label{display:block;font-size:13px;margin-bottom:4px;font-weight:bold}
                .filters select, .filters input{padding:8px;border:1px solid #cbd5e1;border-radius:6px}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="{{ url_for('index') }}" class="btn">← Back to Main Dashboard</a>
                <h2>Admin Monitoring Dashboard</h2>
                <p>Track staff accounts, sales performance, expenses, and activity logs.</p>

                <h3>Staff Sales &amp; Profit Report</h3>
                <table>
                    <tr><th>Staff Member</th><th>Sales Revenue</th><th>COGS (Tracked)</th><th>Gross Profit</th><th>Units Sold</th><th>Total Actions</th></tr>
                    {% for sp in staff_performance %}
                    <tr>
                        <td><strong>{{ sp.staff_name }}</strong></td>
                        <td>{{ "%.2f"|format(sp.revenue) }}</td>
                        <td>{{ "%.2f"|format(sp.tracked_cost) }}</td>
                        <td><strong>{{ "%.2f"|format(sp.gross_profit) }}</strong></td>
                        <td>{{ sp.units_sold }}</td>
                        <td>{{ sp.total_actions }}</td>
                    </tr>
                    {% endfor %}
                </table>

                <h3>Staff Expense Summary</h3>
                <table>
                    <tr><th>Staff Member</th><th>Total Expenses Incurred</th><th>Expense Entries Count</th></tr>
                    {% for ses in staff_expenses_summary %}
                    <tr>
                        <td><strong>{{ ses.username }}</strong></td>
                        <td style="color:#d9534f;font-weight:bold;">{{ "%.2f"|format(ses.total_spent) }}</td>
                        <td>{{ ses.expense_count }}</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="3">No staff expenses recorded yet.</td></tr>
                    {% endfor %}
                </table>

                <h3>Registered Users & Staff Status</h3>
                <table>
                    <tr><th>ID</th><th>Username</th><th>Role</th><th>Status</th><th>Created At</th></tr>
                    {% for u in all_users %}
                    <tr>
                        <td>{{ u.id }}</td>
                        <td><strong>{{ u.username }}</strong></td>
                        <td>{{ u.role }}</td>
                        <td>{{ "Active" if u.is_active else "Disabled" }}</td>
                        <td>{{ u.created_at }}</td>
                    </tr>
                    {% endfor %}
                </table>

                <h3>Staff &amp; Admin Expense Audit Log</h3>
                <form method="get" class="filters">
                    <div>
                        <label for="staff">Filter by Staff Member:</label>
                        <select name="staff" id="staff">
                            <option value="">-- All Staff & Admin --</option>
                            {% for u in all_users %}
                            <option value="{{ u.username }}" {% if selected_staff == u.username %}selected{% endif %}>{{ u.username }} ({{ u.role }})</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label for="date">Filter by Date:</label>
                        <input type="date" name="date" id="date" value="{{ filter_date }}">
                    </div>
                    <div>
                        <button type="submit" style="margin-top:0">Apply Filters</button>
                        <a href="{{ url_for('admin_monitor') }}" class="btn" style="background:#687588;margin-left:5px">Reset</a>
                    </div>
                </form>

                <table>
                    <tr><th>Timestamp</th><th>Staff Member</th><th>Title / Description</th><th>Category</th><th>Amount</th></tr>
                    {% for ex in filtered_expenses %}
                    <tr>
                        <td>{{ ex.created_at }}</td>
                        <td><strong>{{ ex.username }}</strong></td>
                        <td>{{ ex.title }}</td>
                        <td>{{ ex.category }}</td>
                        <td style="color:#d9534f;font-weight:bold;">{{ "%.2f"|format(ex.amount) }}</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="5">No expenses match your filter criteria.</td></tr>
                    {% endfor %}
                </table>

                <h3>Staff Activity Audit Log</h3>
                <table>
                    <tr><th>Timestamp</th><th>Staff Member</th><th>Product Name</th><th>Action</th><th>Quantity</th><th>Unit Price</th></tr>
                    {% for t in filtered_transactions %}
                    <tr>
                        <td>{{ t.created_at }}</td>
                        <td><strong>{{ t.username or 'RIXX' }}</strong></td>
                        <td>{{ t.product_name }} ({{ t.item_id }})</td>
                        <td>{{ t.action }}</td>
                        <td>{{ t.quantity }}</td>
                        <td>{{ "%.2f"|format(t.unit_price) }}</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="6">No activity records match your filter criteria.</td></tr>
                    {% endfor %}
                </table>
            </div>
        </body>
        </html>
    """, all_users=all_users, staff_performance=staff_performance, staff_expenses_summary=staff_expenses_summary, filtered_expenses=filtered_expenses, filtered_transactions=filtered_transactions, selected_staff=selected_staff, filter_date=filter_date)


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    current_user = session.get("username", "RIXX")
    user_role = session.get("role", "staff")

    with connect_db() as db:
        if user_role == "admin":
            products = db.execute("SELECT * FROM products ORDER BY username, name").fetchall()
            if q:
                shown = db.execute("SELECT * FROM products WHERE item_id LIKE ? OR name LIKE ? ORDER BY username, name", (f"%{q}%", f"%{q}%")).fetchall()
            else:
                shown = products
        else:
            products = db.execute("SELECT * FROM products WHERE username = ? ORDER BY name", (current_user,)).fetchall()
            if q:
                shown = db.execute("SELECT * FROM products WHERE username = ? AND (item_id LIKE ? OR name LIKE ?) ORDER BY name", (current_user, f"%{q}%", f"%{q}%")).fetchall()
            else:
                shown = products
        
        if user_role == "admin":
            profit = db.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN action = 'Sale' THEN quantity * unit_price ELSE 0 END), 0) AS sales_revenue,
                    COALESCE(SUM(CASE WHEN action = 'Sale' AND cost_tracked = 1 THEN quantity * unit_cost ELSE 0 END), 0) AS tracked_cost,
                    COALESCE(SUM(CASE WHEN action = 'Sale' AND cost_tracked = 1 THEN quantity * (unit_price - unit_cost) ELSE 0 END), 0) AS gross_profit
                FROM transactions
            """).fetchone()

            exp_row = db.execute("SELECT SUM(amount) AS total FROM expenses").fetchone()
            total_expenses = exp_row["total"] if exp_row and exp_row["total"] is not None else 0.0
        else:
            profit = db.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN action = 'Sale' THEN quantity * unit_price ELSE 0 END), 0) AS sales_revenue,
                    COALESCE(SUM(CASE WHEN action = 'Sale' AND cost_tracked = 1 THEN quantity * unit_cost ELSE 0 END), 0) AS tracked_cost,
                    COALESCE(SUM(CASE WHEN action = 'Sale' AND cost_tracked = 1 THEN quantity * (unit_price - unit_cost) ELSE 0 END), 0) AS gross_profit
                FROM transactions
                WHERE username = ? OR (username IS NULL AND ? = 'RIXX')
            """, (current_user, current_user)).fetchone()

            exp_row = db.execute("SELECT SUM(amount) AS total FROM expenses WHERE username = ?", (current_user,)).fetchone()
            total_expenses = exp_row["total"] if exp_row and exp_row["total"] is not None else 0.0

        net_profit = profit["gross_profit"] - total_expenses

    return render_template_string(
        PAGE,
        products=products,
        shown_products=shown,
        q=q,
        sales_revenue=profit["sales_revenue"],
        tracked_cost=profit["tracked_cost"],
        gross_profit=profit["gross_profit"],
        total_expenses=total_expenses,
        net_profit=net_profit,
        untracked_units=0,
        role=user_role,
        today_date=date.today().isoformat()
    )


@app.post("/add")
def add_product():
    item_id = request.form.get("item_id", "").strip()
    name = request.form.get("name", "").strip()
    current_user = session.get("username", "RIXX")
    try:
        quantity = int(request.form.get("quantity", ""))
        price = float(request.form.get("price", ""))
        cost_price = float(request.form.get("cost_price", ""))
    except ValueError:
        flash("Invalid input fields.", "error")
        return redirect(url_for("index"))

    with connect_db() as db:
        try:
            db.execute("INSERT INTO products (item_id, name, quantity, price, cost_price, username) VALUES (?, ?, ?, ?, ?, ?)", (item_id, name, quantity, price, cost_price, current_user))
            db.execute("INSERT INTO transactions (item_id, product_name, action, quantity, unit_price, unit_cost, cost_tracked, username) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (item_id, name, "Opening stock", quantity, price, cost_price, 0, current_user))
            flash("Product added successfully.")
        except sqlite3.IntegrityError:
            flash("Product ID already exists in your inventory.", "error")
    return redirect(url_for("index"))


@app.post("/sell")
def sell():
    item_id = request.form.get("item_id", "")
    current_user = session.get("username", "RIXX")
    user_role = session.get("role", "staff")
    try:
        quantity = int(request.form.get("quantity", ""))
    except ValueError:
        flash("Invalid quantity.", "error")
        return redirect(url_for("index"))

    with connect_db() as db:
        if user_role == "admin":
            product = db.execute("SELECT * FROM products WHERE item_id = ?", (item_id,)).fetchone()
        else:
            product = db.execute("SELECT * FROM products WHERE item_id = ? AND username = ?", (item_id, current_user)).fetchone()

        if product and product["quantity"] >= quantity:
            db.execute("UPDATE products SET quantity = quantity - ? WHERE item_id = ? AND username = ?", (quantity, item_id, product["username"]))
            db.execute("INSERT INTO transactions (item_id, product_name, action, quantity, unit_price, unit_cost, cost_tracked, username) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (item_id, product["name"], "Sale", quantity, product["price"], product["cost_price"], 1, current_user))
            flash("Sale recorded.")
        else:
            flash("Not enough stock.", "error")
    return redirect(url_for("index"))


@app.post("/restock")
def restock():
    item_id = request.form.get("item_id", "")
    current_user = session.get("username", "RIXX")
    user_role = session.get("role", "staff")
    try:
        quantity = int(request.form.get("quantity", ""))
    except ValueError:
        flash("Invalid quantity.", "error")
        return redirect(url_for("index"))

    with connect_db() as db:
        if user_role == "admin":
            product = db.execute("SELECT * FROM products WHERE item_id = ?", (item_id,)).fetchone()
        else:
            product = db.execute("SELECT * FROM products WHERE item_id = ? AND username = ?", (item_id, current_user)).fetchone()

        if product:
            db.execute("UPDATE products SET quantity = quantity + ? WHERE item_id = ? AND username = ?", (quantity, item_id, product["username"]))
            db.execute("INSERT INTO transactions (item_id, product_name, action, quantity, unit_price, unit_cost, cost_tracked, username) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (item_id, product["name"], "Restock", quantity, product["price"], product["cost_price"], 0, current_user))
            flash("Restocked successfully.")
    return redirect(url_for("index"))


@app.post("/expense")
def add_expense():
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "Other").strip()
    expense_date = request.form.get("expense_date", "").strip()
    current_user = session.get("username", "RIXX")
    try:
        amount = float(request.form.get("amount", ""))
    except ValueError:
        flash("Invalid expense amount.", "error")
        return redirect(url_for("index"))

    if amount < 0 or not title:
        flash("Please provide a valid title and positive amount.", "error")
        return redirect(url_for("index"))

    if expense_date:
        created_at_val = f"{expense_date} {datetime.now().strftime('%H:%M:%S')}"
    else:
        created_at_val = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with connect_db() as db:
        db.execute(
            "INSERT INTO expenses (title, amount, category, username, created_at) VALUES (?, ?, ?, ?, ?)",
            (title, amount, category, current_user, created_at_val)
        )
    flash("Expense recorded successfully.")
    return redirect(url_for("index"))


@app.post("/delete/<item_id>")
def delete_product(item_id):
    current_user = session.get("username", "RIXX")
    user_role = session.get("role", "staff")
    owner = request.args.get("owner", current_user)

    with connect_db() as db:
        if user_role == "admin":
            db.execute("DELETE FROM products WHERE item_id = ? AND username = ?", (item_id, owner))
        else:
            db.execute("DELETE FROM products WHERE item_id = ? AND username = ?", (item_id, current_user))
    flash("Product deleted.")
    return redirect(url_for("index"))


@app.route("/staff", methods=["GET", "POST"])
def manage_staff():
    if session.get("role") != "admin":
        return redirect(url_for("index"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if len(username) >= 3 and len(password) >= 4:
                try:
                    with connect_db() as db:
                        db.execute("INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, 'staff', 1)", (username, generate_password_hash(password)))
                    flash("Staff account created.")
                except sqlite3.IntegrityError:
                    flash("Username taken.", "error")
            else:
                flash("Password must be at least 4 digits/characters.", "error")
        elif action == "toggle":
            uid = request.form.get("user_id")
            with connect_db() as db:
                user = db.execute("SELECT is_active FROM users WHERE id = ?", (uid,)).fetchone()
                if user:
                    new_status = 0 if user["is_active"] else 1
                    db.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, uid))
                    flash("Status updated.")
        return redirect(url_for("manage_staff"))

    with connect_db() as db:
        staff_users = db.execute("SELECT * FROM users ORDER BY id").fetchall()

    return render_template_string("""
        <!doctype html>
        <html lang="en">
        <head><title>Manage Staff</title></head>
        <body style="font-family:Arial;background:#f3f6fa;padding:24px">
            <main style="max-width:700px;margin:auto;background:white;padding:24px;border-radius:12px">
                <a href="{{ url_for('index') }}">← Back to Dashboard</a>
                <h2>Manage Staff Accounts</h2>
                {% for c, m in get_flashed_messages(with_categories=true) %}<p>{{ m }}</p>{% endfor %}
                <form method="post">
                    <input type="hidden" name="action" value="create">
                    <label>Username</label><input name="username" required style="width:100%;padding:8px;margin:6px 0">
                    <label>Password (min 4 digits)</label><input type="password" name="password" required style="width:100%;padding:8px;margin:6px 0">
                    <button type="submit" style="padding:10px;background:#1d5da8;color:white;border:0;border-radius:6px;margin-top:8px">Create Staff Account</button>
                </form>
                <hr style="margin:20px 0">
                <h3>Existing Accounts</h3>
                <table style="width:100%;border-collapse:collapse">
                    <tr><th>Username</th><th>Role</th><th>Status</th><th>Action</th></tr>
                    {% for u in staff_users %}
                    <tr>
                        <td>{{ u.username }}</td>
                        <td>{{ u.role }}</td>
                        <td>{{ "Active" if u.is_active else "Disabled" }}</td>
                        <td>
                            {% if u.role == 'staff' %}
                            <form method="post" style="display:inline">
                                <input type="hidden" name="action" value="toggle">
                                <input type="hidden" name="user_id" value="{{ u.id }}">
                                <button type="submit">{{ "Disable" if u.is_active else "Enable" }}</button>
                            </form>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </main>
        </body></html>
    """, staff_users=staff_users)


@app.route("/export/products")
def export_products():
    current_user = session.get("username", "RIXX")
    user_role = session.get("role", "staff")
    with connect_db() as db:
        if user_role == "admin":
            products = db.execute("SELECT * FROM products ORDER BY username, name").fetchall()
        else:
            products = db.execute("SELECT * FROM products WHERE username = ?", (current_user,)).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    if products:
        writer.writerow(products[0].keys())
        for p in products: writer.writerow([p[k] for p in p.keys()])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=shop_inventory.csv"})


def get_daily_report(report_date, current_user="RIXX", is_admin=True):
    with connect_db() as db:
        if is_admin:
            products = db.execute("""
                SELECT item_id, name, quantity, price, cost_price, username,
                       quantity * price AS retail_value,
                       quantity * cost_price AS stock_cost_value
                FROM products
                ORDER BY username, name
            """).fetchall()

            stock = db.execute("""
                SELECT COUNT(*) AS product_count,
                       COALESCE(SUM(quantity), 0) AS total_units,
                       COALESCE(SUM(quantity * price), 0) AS retail_value,
                       COALESCE(SUM(quantity * cost_price), 0) AS cost_value
                FROM products
            """).fetchone()
        else:
            products = db.execute("""
                SELECT item_id, name, quantity, price, cost_price, username,
                       quantity * price AS retail_value,
                       quantity * cost_price AS stock_cost_value
                FROM products
                WHERE username = ?
                ORDER BY name
            """, (current_user,)).fetchall()

            stock = db.execute("""
                SELECT COUNT(*) AS product_count,
                       COALESCE(SUM(quantity), 0) AS total_units,
                       COALESCE(SUM(quantity * price), 0) AS retail_value,
                       COALESCE(SUM(quantity * cost_price), 0) AS cost_value
                FROM products
                WHERE username = ?
            """, (current_user,)).fetchone()

        all_tx = db.execute("SELECT * FROM transactions").fetchall()
        day_tx = [t for t in all_tx if t["created_at"].startswith(report_date) and (is_admin or (t["username"] or "RIXX") == current_user)]

        revenue = sum(t["quantity"] * t["unit_price"] for t in day_tx if t["action"] == "Sale")
        tracked_cost = sum(t["quantity"] * t["unit_cost"] for t in day_tx if t["action"] == "Sale" and t["cost_tracked"])
        gross_profit = revenue - tracked_cost
        units_sold = sum(t["quantity"] for t in day_tx if t["action"] == "Sale")
        restocked_units = sum(t["quantity"] for t in day_tx if t["action"] == "Restock")
        restock_events = sum(1 for t in day_tx if t["action"] == "Restock")

        daily = {
            "revenue": revenue,
            "tracked_cost": tracked_cost,
            "gross_profit": gross_profit,
            "units_sold": units_sold,
            "restocked_units": restocked_units,
            "restock_events": restock_events
        }

        all_expenses = db.execute("SELECT * FROM expenses").fetchall()
        day_expenses = [e for e in all_expenses if e["created_at"].startswith(report_date) and (is_admin or e["username"] == current_user)]
        daily_expenses_sum = sum(e["amount"] for e in day_expenses)

        staff_sales_map = {}
        for t in day_tx:
            if t["action"] == "Sale":
                s_name = t["username"] or "RIXX"
                if s_name not in staff_sales_map:
                    staff_sales_map[s_name] = {"revenue": 0, "tracked_cost": 0, "gross_profit": 0, "units_sold": 0}
                s_rev = t["quantity"] * t["unit_price"]
                s_cost = (t["quantity"] * t["unit_cost"]) if t["cost_tracked"] else 0
                staff_sales_map[s_name]["revenue"] += s_rev
                staff_sales_map[s_name]["tracked_cost"] += s_cost
                staff_sales_map[s_name]["gross_profit"] += (s_rev - s_cost)
                staff_sales_map[s_name]["units_sold"] += t["quantity"]

        staff_daily_sales = [
            {"staff_name": k, **v} for k, v in staff_sales_map.items()
        ]

        expenses_list = [
            {"created_at": e["created_at"], "username": e["username"], "title": e["title"], "category": e["category"], "amount": e["amount"]}
            for e in sorted(day_expenses, key=lambda x: x["id"], reverse=True)
        ]

        activity = [
            {"created_at": t["created_at"], "username": t["username"], "item_id": t["item_id"], "product_name": t["product_name"], "action": t["action"], "quantity": t["quantity"], "unit_price": t["unit_price"], "unit_cost": t["unit_cost"]}
            for t in sorted(day_tx, key=lambda x: x["id"], reverse=True)
        ]

    return products, stock, daily, daily_expenses_sum, staff_daily_sales, expenses_list, activity


@app.route("/daily-report")
def daily_report():
    report_date = request.args.get("date", date.today().isoformat())
    current_user = session.get("username", "RIXX")
    user_role = session.get("role", "staff")
    is_admin = (user_role == "admin")

    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        flash("Please select a valid report date.", "error")
        return redirect(url_for("daily_report"))

    products, stock, daily, daily_expenses_sum, staff_daily_sales, expenses_list, activity = get_daily_report(report_date, current_user, is_admin)
    gross_p = daily["gross_profit"] if daily and "gross_profit" in daily else 0
    net_daily_profit = gross_p - daily_expenses_sum

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <title>Daily Stock Report</title>
        <style>
            body{font-family:Arial,sans-serif;background:#f3f6fa;color:#202938;margin:0}
            header{background:#17365d;color:white;padding:22px}
            main{max-width:1100px;margin:24px auto;padding:0 16px}
            section{background:white;padding:20px;border-radius:12px;margin-bottom:18px;box-shadow:0 2px 8px #0000000a}
            .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
            .metric{font-size:24px;font-weight:bold;margin-top:8px}
            .small{font-size:13px;color:#687588}
            .tablewrap{overflow-x:auto}
            table{width:100%;border-collapse:collapse}
            th,td{text-align:left;padding:10px;border-bottom:1px solid #e4e9f0}
            th{background:#f7f9fc}
            input,button,.button{font:inherit;padding:10px;border-radius:6px}
            button,.button{background:#1d5da8;color:white;border:0;text-decoration:none;cursor:pointer}
            a{color:#1759a6}
            .actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
        </style>
    </head>
    <body>
    <header>
        <h1>Daily Stock Report</h1>
        <p>Inventory, sales, expenses and summary</p>
    </header>
    <main>
        <p><a href="{{ url_for('index') }}">← Back to Shop Stock</a></p>

        <section>
            <form method="get" class="actions">
                <label for="date">Report date:</label>
                <input id="date" type="date" name="date" value="{{ report_date }}" required>
                <button type="submit">View Report</button>
                <a class="button" href="{{ url_for('daily_report_export', date=report_date) }}">Download CSV</a>
            </form>
        </section>

        <section>
            <h2>Financial Activity on — {{ report_date }}</h2>
            <div class="cards">
                <div>
                    Sales revenue
                    <div class="metric">{{ "%.2f"|format(daily.revenue) }}</div>
                </div>
                <div>
                    Gross profit
                    <div class="metric">{{ "%.2f"|format(daily.gross_profit) }}</div>
                </div>
                <div>
                    Total expenses
                    <div class="metric" style="color:#d9534f">{{ "%.2f"|format(daily_expenses_sum) }}</div>
                </div>
                <div>
                    Net daily profit
                    <div class="metric" style="color:#28a745">{{ "%.2f"|format(net_daily_profit) }}</div>
                </div>
            </div>
        </section>

        <section>
            <h2>Staff Sales &amp; Profit Breakdown for {{ report_date }}</h2>
            <div class="tablewrap">
            <table>
                <thead>
                    <tr><th>Staff Member</th><th>Revenue</th><th>Tracked COGS</th><th>Gross Profit</th><th>Units Sold</th></tr>
                </thead>
                <tbody>
                {% for sds in staff_daily_sales %}
                    <tr>
                        <td><strong>{{ sds.staff_name }}</strong></td>
                        <td>{{ "%.2f"|format(sds.revenue) }}</td>
                        <td>{{ "%.2f"|format(sds.tracked_cost) }}</td>
                        <td><strong>{{ "%.2f"|format(sds.gross_profit) }}</strong></td>
                        <td>{{ sds.units_sold }}</td>
                    </tr>
                {% else %}
                    <tr><td colspan="5">No sales recorded by staff on this date.</td></tr>
                {% endfor %}
                </tbody>
            </table>
            </div>
        </section>

        <section>
            <h2>Expense Log for {{ report_date }}</h2>
            <div class="tablewrap">
            <table>
                <thead>
                    <tr><th>Timestamp</th><th>Staff Member</th><th>Title</th><th>Category</th><th>Amount</th></tr>
                </thead>
                <tbody>
                {% for ex in expenses_list %}
                    <tr>
                        <td>{{ ex.created_at }}</td>
                        <td><strong>{{ ex.username }}</strong></td>
                        <td>{{ ex.title }}</td>
                        <td>{{ ex.category }}</td>
                        <td style="color:#d9534f;font-weight:bold;">{{ "%.2f"|format(ex.amount) }}</td>
                    </tr>
                {% else %}
                    <tr><td colspan="5">No expenses recorded on this date.</td></tr>
                {% endfor %}
                </tbody>
            </table>
            </div>
        </section>

        <section>
            <h2>Current stock summary</h2>
            <div class="cards">
                <div>
                    Products in inventory
                    <div class="metric">{{ stock.product_count }}</div>
                </div>
                <div>
                    Total units in stock
                    <div class="metric">{{ stock.total_units }}</div>
                </div>
                <div>
                    Stock value (Retail)
                    <div class="metric">{{ "%.2f"|format(stock.retail_value) }}</div>
                </div>
                <div>
                    Stock purchase cost
                    <div class="metric">{{ "%.2f"|format(stock.cost_value) }}</div>
                </div>
            </div>
        </section>

        <section>
            <h2>Activity Log for {{ report_date }}</h2>
            <div class="tablewrap">
            <table>
                <thead>
                    <tr><th>Timestamp</th><th>Staff Member</th><th>Product</th><th>Action</th><th>Quantity</th><th>Unit Price</th></tr>
                </thead>
                <tbody>
                {% for t in activity %}
                    <tr>
                        <td>{{ t.created_at }}</td>
                        <td><strong>{{ t.username or 'RIXX' }}</strong></td>
                        <td>{{ t.product_name }} ({{ t.item_id }})</td>
                        <td>{{ t.action }}</td>
                        <td>{{ t.quantity }}</td>
                        <td>{{ "%.2f"|format(t.unit_price) }}</td>
                    </tr>
                {% else %}
                    <tr><td colspan="6">No transactions recorded on this date.</td></tr>
                {% endfor %}
                </tbody>
            </table>
            </div>
        </section>
    </main>
    </body>
    </html>
    """, report_date=report_date, products=products, stock=stock, daily=daily, daily_expenses_sum=daily_expenses_sum, net_daily_profit=net_daily_profit, staff_daily_sales=staff_daily_sales, expenses_list=expenses_list, activity=activity)


@app.route("/daily-report/export")
def daily_report_export():
    report_date = request.args.get("date", date.today().isoformat())
    current_user = session.get("username", "RIXX")
    user_role = session.get("role", "staff")
    is_admin = (user_role == "admin")

    products, stock, daily, daily_expenses_sum, staff_daily_sales, expenses_list, activity = get_daily_report(report_date, current_user, is_admin)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["DAILY STOCK & EXPENSE REPORT", report_date])
    writer.writerow(["Revenue", daily["revenue"]])
    writer.writerow(["Gross Profit", daily["gross_profit"]])
    writer.writerow(["Total Expenses", daily_expenses_sum])
    writer.writerow(["Net Profit", daily["gross_profit"] - daily_expenses_sum])
    writer.writerow([])
    writer.writerow(["EXPENSES ON " + report_date])
    writer.writerow(["Timestamp", "Staff Member", "Title", "Category", "Amount"])
    for ex in expenses_list:
        writer.writerow([ex["created_at"], ex["username"], ex["title"], ex["category"], ex["amount"]])
    writer.writerow([])
    writer.writerow(["TIMESTAMP", "STAFF MEMBER", "ITEM ID", "PRODUCT", "ACTION", "QUANTITY", "UNIT PRICE"])
    for t in activity:
        writer.writerow([t["created_at"], t["username"] or "RIXX", t["item_id"], t["product_name"], t["action"], t["quantity"], t["unit_price"]])

    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=shop_report_{report_date}.csv"}
    )


import os
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
