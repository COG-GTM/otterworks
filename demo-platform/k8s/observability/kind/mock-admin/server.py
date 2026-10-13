"""Stand-in for admin-service on kind: accepts Alertmanager webhooks on
/api/v1/admin/alerts/ingest with the same contract as
services/admin-service/app/controllers/api/v1/admin/alerts_controller.rb
(an `alerts` array; X-Alert-Secret or Bearer auth when ALERT_WEBHOOK_SECRET is set)
and logs every alert it would turn into an incident."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ.get("ALERT_WEBHOOK_SECRET")
RECEIVED = 0


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/metrics":
            return self._send(200, f"mock_admin_alerts_received_total {RECEIVED}\n", "text/plain")
        return self._send(200, {"status": "ok"})

    def do_POST(self):
        global RECEIVED
        if self.path != "/api/v1/admin/alerts/ingest":
            return self._send(404, {"error": "not found"})
        if SECRET:
            auth = self.headers.get("X-Alert-Secret") or self.headers.get("Authorization", "").removeprefix("Bearer ")
            if auth != SECRET:
                return self._send(401, {"error": "Unauthorized"})
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        alerts = payload.get("alerts")
        if not isinstance(alerts, list):
            return self._send(400, {"error": "Missing alerts array"})
        RECEIVED += len(alerts)
        for a in alerts:
            labels = a.get("labels", {})
            print(json.dumps({
                "msg": "incident-from-alert",
                "receiver": payload.get("receiver"),
                "status": a.get("status"),
                "alertname": labels.get("alertname"),
                "severity": labels.get("severity"),
                "affected_service": labels.get("affected_service") or labels.get("service"),
                "namespace": labels.get("namespace"),
                "summary": a.get("annotations", {}).get("summary"),
                "authorized": bool(SECRET),
            }), flush=True)
        return self._send(200, {"received": len(alerts), "processed": len(alerts)})

    def log_message(self, *args):
        pass


HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8089"))), Handler).serve_forever()
