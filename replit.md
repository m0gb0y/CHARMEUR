# CHARMEUR

CHARMEUR (Sensualead) is a Japanese-language marketing site for a men's grooming/lifestyle coaching service. Partner listings are stored in PostgreSQL and served through the Python app.

## Structure

HTML pages with a small Flask API — no frontend build step:

- `index.html` — main landing page
- `partners.html` — affiliated partners & lessons page
- `admin.html` — password-gated partner management interface at `/admin`
- `server.py` — static page serving, partner API, and signed admin sessions
- `privacy.html` — privacy policy
- `terms.html` — terms of service
- `tokushoho.html` — legal disclosure page (特定商取引法)

## Running the project

The `Start application` workflow runs `python3 server.py` on port 5000. Production uses Gunicorn with the same Flask app. Partner records are stored in the Replit PostgreSQL database.

Set `PARTNER_ADMIN_PASSWORD` as a Replit Secret before using `/admin`. `SESSION_SECRET` signs the short-lived, HTTP-only admin session cookie. Do not put either value in source code.

## User preferences

None recorded yet.
