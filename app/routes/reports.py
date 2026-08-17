from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from sqlalchemy import func
from app import db
from app.models import Trip, Transporter, Plant
from app.utils import generate_csv

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


@reports_bp.route("/")
@login_required
def index():
    return render_template("reports/index.html")


@reports_bp.route("/trip-wise")
@login_required
def trip_wise():
    query = Trip.query
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    if date_from:
        query = query.filter(Trip.date >= datetime.strptime(date_from, "%Y-%m-%d").date())
    if date_to:
        query = query.filter(Trip.date <= datetime.strptime(date_to, "%Y-%m-%d").date())
    trips = query.options(
        db.joinedload(Trip.transporter),
        db.joinedload(Trip.plant),
        db.joinedload(Trip.mine),
    ).order_by(Trip.date.desc()).all()

    if request.args.get("export") == "csv":
        headers = ["Date", "Truck", "Work Order", "Mines Name", "Mines Qty", "Plant", "Transporter", "Freight", "TDS%", "TDS Amt", "Expense", "Paid", "Balance", "Status"]
        rows = [
            [
                t.date,
                t.lorry_number,
                t.mine.name if t.mine else "",
                t.mine.name if t.mine else "",
                float(t.mines_qty) if t.mines_qty else "",
                t.plant.name if t.plant else "",
                t.transporter.name if t.transporter else "",
                float(t.total_freight),
                float(t.tds_percent),
                float(t.tds_amount),
                float(t.total_expense),
                float(t.total_paid),
                float(t.balance),
                t.status,
            ]
            for t in trips
        ]
        return generate_csv(headers, rows)

    return render_template("reports/trip_wise.html", trips=trips, date_from=date_from, date_to=date_to)


@reports_bp.route("/transporter-wise")
@login_required
def transporter_wise():
    rows = (
        db.session.query(
            Transporter.id,
            Transporter.name,
            func.count(Trip.id),
            func.coalesce(func.sum(Trip.total_freight), 0),
            func.coalesce(func.sum(Trip.total_paid), 0),
            func.coalesce(func.sum(Trip.total_expense), 0),
            func.coalesce(func.sum(Trip.tds_amount), 0),
            func.coalesce(func.sum(Trip.balance), 0),
        )
        .join(Trip, Trip.transporter_id == Transporter.id)
        .group_by(Transporter.id, Transporter.name)
        .order_by(Transporter.name)
        .all()
    )
    data = [
        {
            "transporter": name,
            "trip_count": int(count),
            "total_freight": float(freight),
            "total_paid": float(paid),
            "total_expense": float(expense),
            "total_tds": float(tds),
            "total_balance": float(balance),
        }
        for _tid, name, count, freight, paid, expense, tds, balance in rows
    ]

    if request.args.get("export") == "csv":
        headers = ["Transporter", "Trips", "Freight", "Paid", "Expense", "TDS", "Balance"]
        rows_out = [
            [d["transporter"], d["trip_count"], d["total_freight"], d["total_paid"],
             d["total_expense"], d["total_tds"], d["total_balance"]]
            for d in data
        ]
        return generate_csv(headers, rows_out)

    return render_template("reports/transporter_wise.html", data=data)


@reports_bp.route("/date-wise")
@login_required
def date_wise():
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    q = db.session.query(
        Trip.date,
        func.count(Trip.id),
        func.coalesce(func.sum(Trip.total_freight), 0),
        func.coalesce(func.sum(Trip.total_paid), 0),
        func.coalesce(func.sum(Trip.total_expense), 0),
        func.coalesce(func.sum(Trip.tds_amount), 0),
        func.coalesce(func.sum(Trip.balance), 0),
    )
    if date_from:
        q = q.filter(Trip.date >= datetime.strptime(date_from, "%Y-%m-%d").date())
    if date_to:
        q = q.filter(Trip.date <= datetime.strptime(date_to, "%Y-%m-%d").date())
    rows = q.group_by(Trip.date).order_by(Trip.date.desc()).all()

    summary = [
        {
            "date": d.isoformat(),
            "trip_count": int(count),
            "total_freight": float(freight),
            "total_paid": float(paid),
            "total_expense": float(expense),
            "total_tds": float(tds),
            "total_balance": float(balance),
        }
        for d, count, freight, paid, expense, tds, balance in rows
    ]

    if request.args.get("export") == "csv":
        headers = ["Date", "Trips", "Freight", "Paid", "Expense", "TDS", "Balance"]
        rows_out = [
            [s["date"], s["trip_count"], s["total_freight"], s["total_paid"],
             s["total_expense"], s["total_tds"], s["total_balance"]]
            for s in summary
        ]
        return generate_csv(headers, rows_out)

    return render_template("reports/date_wise.html", summary=summary, date_from=date_from, date_to=date_to)


@reports_bp.route("/plant-wise")
@login_required
def plant_wise():
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    plants = Plant.query.order_by(Plant.name).all()
    plant_ids = {p.id for p in plants}

    q = Trip.query.filter(Trip.plant_id.isnot(None)).options(
        db.joinedload(Trip.mine),
        db.joinedload(Trip.transporter),
    )
    if date_from:
        q = q.filter(Trip.date >= datetime.strptime(date_from, "%Y-%m-%d").date())
    if date_to:
        q = q.filter(Trip.date <= datetime.strptime(date_to, "%Y-%m-%d").date())
    trips = q.order_by(Trip.date.desc()).all()

    by_plant = {}
    for t in trips:
        if t.plant_id not in plant_ids:
            continue
        by_plant.setdefault(t.plant_id, []).append(t)

    hierarchy = []
    for p in plants:
        ptrips = by_plant.get(p.id, [])
        if not ptrips:
            continue
        lorry_groups = {}
        for t in ptrips:
            lorry_groups.setdefault(t.lorry_number, []).append(t)

        lorry_data = []
        plant_freight = plant_paid = plant_expense = plant_tds = plant_balance = 0
        for lorry, lt in sorted(lorry_groups.items()):
            lorry_freight = sum(float(x.total_freight) for x in lt)
            lorry_paid = sum(float(x.total_paid) for x in lt)
            lorry_expense = sum(float(x.total_expense) for x in lt)
            lorry_tds = sum(float(x.tds_amount) for x in lt)
            lorry_balance = sum(float(x.balance) for x in lt)
            lorry_data.append({
                "lorry": lorry,
                "trips": lt,
                "trip_count": len(lt),
                "freight": lorry_freight,
                "paid": lorry_paid,
                "expense": lorry_expense,
                "tds": lorry_tds,
                "balance": lorry_balance,
            })
            plant_freight += lorry_freight
            plant_paid += lorry_paid
            plant_expense += lorry_expense
            plant_tds += lorry_tds
            plant_balance += lorry_balance

        hierarchy.append({
            "plant": p,
            "trip_count": len(ptrips),
            "freight": plant_freight,
            "paid": plant_paid,
            "expense": plant_expense,
            "tds": plant_tds,
            "balance": plant_balance,
            "lorries": lorry_data,
        })

    if request.args.get("export") == "csv":
        headers = ["Plant", "Truck", "Work Order", "Mines Name", "Mines Qty", "Date", "Transporter", "Freight", "TDS%", "TDS Amt", "Expense", "Paid", "Balance", "Status"]
        rows = []
        for h in hierarchy:
            for l in h["lorries"]:
                for t in l["trips"]:
                    rows.append([
                        h["plant"].name,
                        l["lorry"],
                        t.mine.name if t.mine else "",
                        t.mine.name if t.mine else "",
                        float(t.mines_qty) if t.mines_qty else "",
                        t.date,
                        t.transporter.name if t.transporter else "",
                        float(t.total_freight),
                        float(t.tds_percent),
                        float(t.tds_amount),
                        float(t.total_expense),
                        float(t.total_paid),
                        float(t.balance),
                        t.status,
                    ])
        return generate_csv(headers, rows)

    return render_template("reports/plant_wise.html", hierarchy=hierarchy, date_from=date_from, date_to=date_to)
