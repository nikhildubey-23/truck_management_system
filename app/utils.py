import csv
import io
from datetime import datetime
from flask import Response
from flask_login import current_user
from app import db
from app.models import AuditLog


def log_audit(action, entity_type, entity_id=None, details=None, user_id=None):
    if user_id is None:
        try:
            user_id = current_user.id if current_user.is_authenticated else None
        except Exception:
            user_id = None
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.session.add(log)


def validate_positive(value, name):
    try:
        v = float(value)
        if v < 0:
            raise ValueError(f"{name} cannot be negative")
        return v
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {name}")


def generate_csv(headers, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"},
    )
