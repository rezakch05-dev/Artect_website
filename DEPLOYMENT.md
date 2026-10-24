# Artect production deployment and Gmail notifications

## 1. Install dependencies

Use Python 3.10 or newer. On a Linux production host, run from this directory:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-production.txt
```

## 2. Set required environment variables

Set variables in your hosting control panel or a service-manager environment file. Do not put real credentials in source code, HTML, SQLite, or a public repository.

- `ARTECT_ENV=production`
- `ARTECT_SECRET_KEY`: generate a unique stable key with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Do not regenerate it every restart and do not share it publicly.
- `ARTECT_SMTP_PASSWORD`: a Gmail App Password, not the normal Gmail account password. Remove spaces when pasting it.

Optional first-run variables for an empty database are `ARTECT_BOOTSTRAP_ADMIN_USERNAME` and `ARTECT_BOOTSTRAP_ADMIN_PASSWORD` (minimum 14 characters). Alternatively, create/reset an admin account using the command in section 4 before starting the web server.

The `.env.example` file contains placeholders only and is not automatically loaded. Configure actual environment variables through the hosting provider or your service manager.

## 3. Gmail SMTP settings in `/admin/settings`

- SMTP Host: `smtp.gmail.com`
- SMTP Port: `587`
- SMTP User: your full Gmail address
- SMTP From: the same Gmail address, unless a verified Gmail alias is configured
- Admin email: the destination inbox that should receive contact/Demo notifications
- Use STARTTLS (the application uses it by default on port 587)

First, enable Google 2-Step Verification and create an App Password in Google Account security settings. Put that App Password only in `ARTECT_SMTP_PASSWORD`. It is deliberately not accepted by the settings form and is not stored in SQLite. Existing legacy `smtp_password` rows are removed at application startup.

If `smtp_user` is configured but `ARTECT_SMTP_PASSWORD` is missing, the application logs a delivery error and leaves the contact record stored in the admin message panel.

## 4. Set the admin password

Run interactively on the server (from this directory):

```bash
python manage_admin_password.py admin
```

Use a unique password of at least 14 characters. The password is not passed as a command-line argument or written to logs. Back up `database/artect.db` before deploying any update.

## 5. Start with a WSGI server

Do not use `python app.py` as a public production server. With the environment variables set, run behind an HTTPS reverse proxy:

```bash
gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:app
```

Configure the reverse proxy/hosting panel to forward the public hostname to port 8000 and serve HTTPS. Make sure the SQLite database and upload/model directories live on persistent writable storage and are included in backups. The application intentionally refuses to start in production if `ARTECT_SECRET_KEY` is missing/too short.

## 6. Verify after deployment

1. Sign in to `/admin` with the reset account.
2. Check `/admin/settings` and confirm it reports that the SMTP App Password is configured.
3. Submit a test message through `/contact`; confirm it appears at `/admin/messages` and arrives in Gmail Inbox (also check Spam).
4. If notification delivery fails, inspect server logs for the SMTP error. No SMTP password is included in the log message.
5. Test all editor actions, uploads, theme selection, 3D viewers, annotation interactions, mobile layouts, and sign-out. All unsafe form/AJAX requests require a CSRF token; the application inserts it into rendered forms and same-origin fetch requests.
