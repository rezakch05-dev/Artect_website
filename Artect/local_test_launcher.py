#!/usr/bin/env python3
"""Local-only launcher for Windows functional testing.

This helper sets development environment variables, creates a stable local-only
Flask secret, optionally asks for a Gmail App Password without echoing or saving
it, and assigns a known local-testing password to `admin` only on first setup.
Never use the local credentials or this launcher for a public production service.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'database' / 'artect.db'
LOCAL_SECRET_PATH = BASE_DIR / '.artect-local-secret'
ADMIN_READY_PATH = BASE_DIR / '.artect-local-admin-ready'
LOCAL_ADMIN_PASSWORD = 'ArtectLocal@2026!'


def prepare_environment() -> dict[str, str]:
    env = os.environ.copy()
    env['ARTECT_ENV'] = 'development'
    env['ARTECT_DEV_HOST'] = '127.0.0.1'
    env.setdefault('PORT', '5000')
    env.pop('ARTECT_SMTP_PASSWORD', None)

    secret = ''
    try:
        secret = LOCAL_SECRET_PATH.read_text(encoding='utf-8').strip()
    except OSError:
        pass
    if len(secret) < 48:
        secret = secrets.token_urlsafe(48)
        LOCAL_SECRET_PATH.write_text(secret + '\n', encoding='utf-8')
        try:
            LOCAL_SECRET_PATH.chmod(0o600)
        except OSError:
            # Windows permissions are inherited from the local project folder.
            pass
    env['ARTECT_SECRET_KEY'] = secret
    return env


def initialize_default_local_admin(env: dict[str, str]) -> bool:
    """Set the predictable local test password once; preserve later changes."""
    if ADMIN_READY_PATH.exists():
        return False

    # Initialize only the administrator table here. The application will run its
    # normal schema migrations when the server starts; this avoids importing the
    # Flask app twice just to seed the local test credential.
    from werkzeug.security import generate_password_hash

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            status INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_owner INTEGER DEFAULT 0
        )""")
        columns = {r[1] for r in conn.execute('PRAGMA table_info(admin_users)')}
        if 'is_owner' not in columns:
            conn.execute('ALTER TABLE admin_users ADD COLUMN is_owner INTEGER DEFAULT 0')
            columns.add('is_owner')
        row = conn.execute('SELECT id FROM admin_users WHERE username=?', ('admin',)).fetchone()
        password_hash = generate_password_hash(LOCAL_ADMIN_PASSWORD)
        if row:
            conn.execute('UPDATE admin_users SET password_hash=?, status=1 WHERE id=?', (password_hash, row[0]))
            admin_id = row[0]
        else:
            if 'is_owner' in columns:
                conn.execute('INSERT INTO admin_users(username,password_hash,status,is_owner) VALUES(?,?,1,1)',
                              ('admin', password_hash))
            else:
                conn.execute('INSERT INTO admin_users(username,password_hash,status) VALUES(?,?,1)',
                              ('admin', password_hash))
            admin_id = conn.execute('SELECT id FROM admin_users WHERE username=?', ('admin',)).fetchone()[0]
        if 'is_owner' in columns:
            existing_owner = conn.execute('SELECT id FROM admin_users WHERE COALESCE(is_owner,0)=1 LIMIT 1').fetchone()
            if not existing_owner:
                conn.execute('UPDATE admin_users SET is_owner=1 WHERE id=?', (admin_id,))
        conn.commit()

    ADMIN_READY_PATH.write_text('Local admin initialization completed.\n', encoding='utf-8')
    try:
        ADMIN_READY_PATH.chmod(0o600)
    except OSError:
        pass
    print('\nFirst-run local administrator account configured:')
    print('  Username: admin')
    print(f'  Password: {LOCAL_ADMIN_PASSWORD}')
    print('This default is for LOCAL TESTING ONLY. Do not deploy it to the internet.')
    print('The launcher will not reset the admin password again unless its local marker is removed.')
    return True


def prompt_for_gmail(env: dict[str, str]) -> None:
    print('\nGmail notification test is optional.')
    print('Choose Yes only if you already created a Google App Password. Do not enter your normal Gmail password.')
    try:
        choice = input('Enable Gmail notifications for this run? [y/N]: ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if choice not in {'y', 'yes'}:
        print('Gmail SMTP is not enabled for this run; contact messages can still be tested in the admin panel.')
        return
    try:
        value = getpass.getpass('Enter Gmail App Password (input is hidden; spaces are ignored): ').replace(' ', '').strip()
    except (EOFError, KeyboardInterrupt):
        print('\nGmail setup cancelled.')
        return
    if value:
        env['ARTECT_SMTP_PASSWORD'] = value
        print('Gmail App Password loaded into this process only; it will not be written to project files or SQLite.')
    else:
        print('No App Password entered; Gmail notifications are disabled for this run.')


def main() -> int:
    env = prepare_environment()
    try:
        initialize_default_local_admin(env)
    except Exception as exc:
        print(f'\nCould not prepare the local admin account: {exc}', file=sys.stderr)
        print('You can reset it manually with: python manage_admin_password.py admin', file=sys.stderr)
        return 1

    prompt_for_gmail(env)
    print('\nStarting local Artect server...')
    print('Website: http://127.0.0.1:5000')
    print('Admin:   http://127.0.0.1:5000/admin')
    print('Stop the server with Ctrl+C. Keep this window open while testing.\n')
    try:
        completed = subprocess.run([sys.executable, '-u', 'app.py'], cwd=str(BASE_DIR), env=env)
        return int(completed.returncode)
    except KeyboardInterrupt:
        print('\nLocal server stopped.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
