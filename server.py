#!/usr/bin/env python3
"""Simple static file server for the CHARMEUR site, bound for Replit preview."""
import http.server
import socketserver

PORT = 5000

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Avoid stale content in the Replit preview iframe during development.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving on 0.0.0.0:{PORT}")
        httpd.serve_forever()
