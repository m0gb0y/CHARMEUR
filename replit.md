# CHARMEUR

CHARMEUR (Sensualead) is a Japanese-language static marketing site for a men's grooming/lifestyle coaching service.

## Structure

Plain static HTML — no build step, no framework, no package.json:

- `index.html` — main landing page
- `partners.html` — affiliated partners & lessons page
- `privacy.html` — privacy policy
- `terms.html` — terms of service
- `tokushoho.html` — legal disclosure page (特定商取引法)

## Running the project

Served via `server.py`, a small Python `http.server` wrapper bound to `0.0.0.0:5000` with cache disabled (so preview edits show immediately). The `Start application` workflow runs `python3 server.py`.

## User preferences

None recorded yet.
