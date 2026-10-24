#!/usr/bin/env python3
"""Create or reset an Artect administrator password interactively.

Run from the application directory after installing requirements:
    python manage_admin_password.py admin
The password is never accepted as a command-line argument or printed.
"""
import argparse
import getpass
import os
import sqlite3
import sys
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database', 'artect.db')


def main() -> int:
    parser = argparse.ArgumentParser(description='Create/reset an Artect administrator password.')
    parser.add_argument('username', help='Administrator username to create or reset')
    args = parser.parse_args()
    username = args.username.strip()
    if not username or len(username) > 80:
        print('Invalid username.', file=sys.stderr)
        return 2
    first = getpass.getpass('New password (minimum 14 characters): ')
    second = getpass.getpass('Repeat new password: ')
    if len(first) < 14:
        print('Password must be at least 14 characters.', file=sys.stderr)
        return 2
    if first != second:
        print('Passwords do not match.', file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            status INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_owner INTEGER DEFAULT 0
        )""")
        cols = {row[1] for row in conn.execute('PRAGMA table_info(admin_users)')}
        if 'is_owner' not in cols:
            conn.execute('ALTER TABLE admin_users ADD COLUMN is_owner INTEGER DEFAULT 0')
        owner_exists = conn.execute('SELECT 1 FROM admin_users WHERE COALESCE(is_owner,0)=1 LIMIT 1').fetchone() is not None
        current = conn.execute('SELECT id FROM admin_users WHERE username=?', (username,)).fetchone()
        password_hash = generate_password_hash(first)
        if current:
            conn.execute('UPDATE admin_users SET password_hash=?, status=1 WHERE id=?', (password_hash, current[0]))
            if not owner_exists:
                conn.execute('UPDATE admin_users SET is_owner=1 WHERE id=?', (current[0],))
            action = 'reset'
        else:
            conn.execute('INSERT INTO admin_users(username,password_hash,status,is_owner) VALUES(?,?,1,?)',
                         (username, password_hash, 0 if owner_exists else 1))
            action = 'created'
        conn.commit()
    print(f'Administrator account {action} successfully. Store the new password in your password manager.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
