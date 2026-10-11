import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "shop_manager_secret_key_123")

# Get database URL from Render or fallback to local SQLite for testing
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    if DATABASE_URL:
        # Connect to Render PostgreSQL
        db = getattr(g, "_database", None)
        if db is None:
            db = g._database = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return db
    else:
        # Fallback local sqlite if needed
        import sqlite3
        db = getattr(g, "_database", None)
        if db is None:
            db = g._database = sqlite3.connect("stock.db")
            db.row_factory = sqlite3.Row
        return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor() if DATABASE_URL else db
        
        # Create Users Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        
        # Create Products Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL
            )
        """)
        
        # Create Transactions Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                product_id INTEGER,
                type TEXT,
                qty INTEGER,
                total REAL,
                date TEXT
            )
        """)
        
        # Create Expenses Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                description TEXT,
                amount REAL,
                date TEXT
            )
        """)
        if DATABASE_URL:
            db.commit()
        else:
            db.commit()

init_db()
