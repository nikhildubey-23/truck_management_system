from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from app import db
from app.models import Transporter
from app.utils import log_audit

transporters_bp = Blueprint("transporters", __name__, url_prefix="/transporters")
PER_PAGE = 20


@transporters_bp.route("/")
@login_required
def list():
    page = request.args.get("page", 1, type=int)
    query = Transporter.query
    search = request.args.get("search", "")
    if search:
        query = query.filter(Transporter.name.ilike(f"%{search}%"))
    pagination = query.order_by(Transporter.name).paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template(
        "transporters/list.html",
        transporters=pagination.items,
        pagination=pagination,
        search=search,
    )


@transporters_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name:
                flash("Transporter name is required", "danger")
                return render_template("transporters/form.html", transporter=None)
            if Transporter.query.filter_by(name=name).first():
                flash("Transporter with this name already exists", "danger")
                return render_template("transporters/form.html", transporter=None)
            t = Transporter(
                name=name,
                pan_card=request.form.get("pan_card", "").strip(),
                bank_account=request.form.get("bank_account", "").strip(),
                ifsc_code=request.form.get("ifsc_code", "").strip(),
                contact=request.form.get("contact", "").strip(),
            )
            db.session.add(t)
            db.session.flush()
            log_audit("create", "transporter", t.id, f"Created transporter: {t.name}")
            db.session.commit()
            flash("Transporter added successfully", "success")
            return redirect(url_for("transporters.list"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
    return render_template("transporters/form.html", transporter=None)


@transporters_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    t = Transporter.query.get_or_404(id)
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name:
                flash("Transporter name is required", "danger")
                return render_template("transporters/form.html", transporter=t)
            existing = Transporter.query.filter(Transporter.name == name, Transporter.id != id).first()
            if existing:
                flash("Transporter with this name already exists", "danger")
                return render_template("transporters/form.html", transporter=t)
            t.name = name
            t.pan_card = request.form.get("pan_card", "").strip()
            t.bank_account = request.form.get("bank_account", "").strip()
            t.ifsc_code = request.form.get("ifsc_code", "").strip()
            t.contact = request.form.get("contact", "").strip()
            log_audit("update", "transporter", t.id, f"Updated transporter: {t.name}")
            db.session.commit()
            flash("Transporter updated successfully", "success")
            return redirect(url_for("transporters.list"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
    return render_template("transporters/form.html", transporter=t)


@transporters_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    t = Transporter.query.get_or_404(id)
    try:
        db.session.delete(t)
        log_audit("delete", "transporter", id, f"Deleted transporter: {t.name}")
        db.session.commit()
        flash("Transporter deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Cannot delete: {str(e)}", "danger")
    return redirect(url_for("transporters.list"))


@transporters_bp.route("/api")
@login_required
def api():
    transporters = Transporter.query.order_by(Transporter.name).all()
    return jsonify([t.to_dict() for t in transporters])
