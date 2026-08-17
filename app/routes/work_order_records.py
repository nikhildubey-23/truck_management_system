import csv, io, os, json
import requests
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required
from app import db
from app.models import WorkOrder, Mine, PetrolStation
from app.utils import log_audit, generate_csv

work_order_fields = [
    ("date", "Date", "date"),
    ("lorry_number", "Truck #", "text"),
    ("work_order_number", "WO Number", "text"),
    ("mine_name", "Mine Name", "text"),
    ("account_name", "Account Name", "text"),
    ("remark", "Remark", "text"),
    ("tds", "TDS", "number"),
    ("ddtds", "DD TDS Date", "date"),
    ("account_advance", "Acc Adv", "number"),
    ("mines_qty", "Mines Qty", "number"),
    ("plant_qty", "Plant Qty", "number"),
    ("rate", "Rate", "number"),
    ("cash", "Cash", "number"),
    ("loading", "Loading", "number"),
    ("total_advance", "Total Advance", "number"),
    ("shortage", "Shortage", "number"),
    ("short_amt", "Short Amt", "number"),
    ("munsiyana", "Munsiyana", "number"),
    ("rtgs", "RTGS", "number"),
    ("petrol", "Petrol (Name:Amt,...)", "text"),
]

work_order_records_bp = Blueprint("work_order_records", __name__, url_prefix="/work-orders")

PER_PAGE = 20


@work_order_records_bp.route("/")
@login_required
def work_orders():
    page = request.args.get("page", 1, type=int)
    mine_id = request.args.get("mine_id", "", type=str)
    query = WorkOrder.query
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    lorry = request.args.get("lorry", "")
    status = request.args.get("status", "")
    account = request.args.get("account", "")
    if mine_id:
        query = query.filter_by(mine_id=int(mine_id))
    if date_from:
        query = query.filter(WorkOrder.date >= datetime.strptime(date_from, "%Y-%m-%d").date())
    if date_to:
        query = query.filter(WorkOrder.date <= datetime.strptime(date_to, "%Y-%m-%d").date())
    if lorry:
        query = query.filter(WorkOrder.lorry_number.ilike(f"%{lorry}%"))
    if status:
        query = query.filter(WorkOrder.status == status)
    if account:
        query = query.filter(WorkOrder.account_name.ilike(f"%{account}%"))

    if request.args.get("export") == "csv":
        all_work_orders = query.order_by(WorkOrder.date.desc()).all()
        headers = ["WO #", "Date", "Truck", "Mine", "Account", "TDS", "DD TDS Date", "Acc Adv", "Mines Qty", "Plant Qty", "Rate", "Freight", "Cash", "Loading", "Advance", "Shortage", "Short Amt", "Munsiyana", "RTGS", "Balance", "Status", "Remark"]
        rows = [
            [
                wo.work_order_number or "",
                wo.date,
                wo.lorry_number,
                wo.mine.name if wo.mine else "",
                wo.account_name or "",
                float(wo.tds), wo.ddtds.isoformat() if wo.ddtds else "", float(wo.account_advance),
                float(wo.mines_qty) if wo.mines_qty else "",
                float(wo.plant_qty) if wo.plant_qty else "",
                float(wo.rate), float(wo.total_freight),
                float(wo.cash), float(wo.loading), float(wo.total_advance),
                float(wo.shortage) if wo.shortage else "",
                float(wo.short_amt), float(wo.munsiyana), float(wo.rtgs),
                float(wo.balance), wo.status, wo.remark or "",
            ]
            for wo in all_work_orders
        ]
        return generate_csv(headers, rows)

    query = query.options(
        db.joinedload(WorkOrder.mine).joinedload(Mine.plant),
        db.selectinload(WorkOrder.petrol_stations),
    )
    all_work_orders = query.order_by(WorkOrder.mine_id.asc(), WorkOrder.date.desc()).all()

    mine_groups = {}
    for wo in all_work_orders:
        key = wo.mine_id or 0
        if key not in mine_groups:
            mine = wo.mine
            plant = mine.plant if mine else None
            mine_groups[key] = {
                "mine": mine,
                "mine_name": mine.name if mine else "Unassigned",
                "plant_name": plant.name if plant else "",
                "work_orders": [],
            }
        mine_groups[key]["work_orders"].append(wo)

    grouped = list(mine_groups.values())
    total_count = len(all_work_orders)

    mine = None
    if mine_id:
        mine = Mine.query.get(int(mine_id))

    return render_template(
        "work_order_records/list.html",
        grouped=grouped,
        total_count=total_count,
        date_from=date_from,
        date_to=date_to,
        lorry=lorry,
        status=status,
        account=account,
        mine_id=mine_id,
        mine=mine,
    )


@work_order_records_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    mines = Mine.query.order_by(Mine.name).all()
    if request.method == "POST":
        try:
            date_str = request.form.get("date", "").strip()
            lorry_number = request.form.get("lorry_number", "").strip()
            if not date_str or not lorry_number:
                flash("Date and Lorry Number are required", "danger")
                return render_template("work_order_records/form.html", work_order=None, mines=mines)

            wo = WorkOrder(
                date=datetime.strptime(date_str, "%Y-%m-%d").date(),
                lorry_number=lorry_number,
                work_order_number=request.form.get("work_order_number", "").strip() or None,
                mine_id=int(request.form.get("mine_id")) if request.form.get("mine_id") else None,
                tds=float(request.form.get("tds", 0) or 0),
                ddtds=datetime.strptime(request.form.get("ddtds", "").strip(), "%Y-%m-%d").date() if request.form.get("ddtds", "").strip() else None,
                account_advance=float(request.form.get("account_advance", 0) or 0),
                mines_qty=float(request.form.get("mines_qty", 0) or 0),
                plant_qty=float(request.form.get("plant_qty", 0) or 0),
                rate=float(request.form.get("rate", 0) or 0),
                total_freight=0,
                cash=float(request.form.get("cash", 0) or 0),
                loading=float(request.form.get("loading", 0) or 0),
                total_advance=float(request.form.get("total_advance", 0) or 0),
                shortage=float(request.form.get("shortage", 0) or 0),
                short_amt=float(request.form.get("short_amt", 0) or 0),
                munsiyana=float(request.form.get("munsiyana", 0) or 0),
                balance=0,
                rtgs=float(request.form.get("rtgs", 0) or 0),
                account_name=request.form.get("account_name", "").strip(),
                remark=request.form.get("remark", "").strip(),
            )
            wo.recalculate()
            db.session.add(wo)
            db.session.flush()

            petrol_names = request.form.getlist("petrol_name[]")
            petrol_amounts = request.form.getlist("petrol_amount[]")
            for i, pname in enumerate(petrol_names):
                pname = pname.strip()
                if pname:
                    amt = float(petrol_amounts[i]) if i < len(petrol_amounts) and petrol_amounts[i] else 0
                    db.session.add(PetrolStation(work_order_id=wo.id, name=pname, amount=amt))

            db.session.flush()
            log_audit("create", "work_order", wo.id, f"Created work order: {wo.lorry_number} on {wo.date}")
            db.session.commit()
            flash("Work order added successfully", "success")
            next_url = request.form.get("next", "")
            if next_url:
                return redirect(next_url)
            mine_id = request.form.get("mine_id", "")
            if mine_id:
                return redirect(url_for("mines.view", id=int(mine_id)))
            return redirect(url_for("work_order_records.work_orders"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
    return render_template("work_order_records/form.html", work_order=None, mines=mines)


@work_order_records_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    wo = WorkOrder.query.get_or_404(id)
    mines = Mine.query.order_by(Mine.name).all()
    if request.method == "POST":
        try:
            date_str = request.form.get("date", "").strip()
            lorry_number = request.form.get("lorry_number", "").strip()
            if not date_str or not lorry_number:
                flash("Date and Lorry Number are required", "danger")
                return render_template("work_order_records/form.html", work_order=wo, mines=mines)

            wo.date = datetime.strptime(date_str, "%Y-%m-%d").date()
            wo.lorry_number = lorry_number
            wo.work_order_number = request.form.get("work_order_number", "").strip() or None
            wo.mine_id = int(request.form.get("mine_id")) if request.form.get("mine_id") else None
            wo.tds = float(request.form.get("tds", 0) or 0)
            wo.ddtds = datetime.strptime(request.form.get("ddtds", "").strip(), "%Y-%m-%d").date() if request.form.get("ddtds", "").strip() else None
            wo.account_advance = float(request.form.get("account_advance", 0) or 0)
            wo.mines_qty = float(request.form.get("mines_qty", 0) or 0)
            wo.plant_qty = float(request.form.get("plant_qty", 0) or 0)
            wo.rate = float(request.form.get("rate", 0) or 0)
            wo.cash = float(request.form.get("cash", 0) or 0)
            wo.loading = float(request.form.get("loading", 0) or 0)
            wo.total_advance = float(request.form.get("total_advance", 0) or 0)
            wo.shortage = float(request.form.get("shortage", 0) or 0)
            wo.short_amt = float(request.form.get("short_amt", 0) or 0)
            wo.munsiyana = float(request.form.get("munsiyana", 0) or 0)
            wo.rtgs = float(request.form.get("rtgs", 0) or 0)
            wo.account_name = request.form.get("account_name", "").strip()
            wo.remark = request.form.get("remark", "").strip()
            wo.recalculate()

            PetrolStation.query.filter_by(work_order_id=wo.id).delete()
            petrol_names = request.form.getlist("petrol_name[]")
            petrol_amounts = request.form.getlist("petrol_amount[]")
            for i, pname in enumerate(petrol_names):
                pname = pname.strip()
                if pname:
                    amt = float(petrol_amounts[i]) if i < len(petrol_amounts) and petrol_amounts[i] else 0
                    db.session.add(PetrolStation(work_order_id=wo.id, name=pname, amount=amt))

            log_audit("update", "work_order", wo.id, f"Updated work order: {wo.lorry_number}")
            db.session.commit()
            flash("Work order updated successfully", "success")
            return redirect(url_for("work_order_records.work_orders"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
    return render_template("work_order_records/form.html", work_order=wo, mines=mines)


@work_order_records_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    wo = WorkOrder.query.get_or_404(id)
    try:
        PetrolStation.query.filter_by(work_order_id=wo.id).delete()
        db.session.delete(wo)
        log_audit("delete", "work_order", id, f"Deleted work order: {wo.lorry_number}")
        db.session.commit()
        flash("Work order deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Cannot delete: {str(e)}", "danger")
    return redirect(url_for("work_order_records.work_orders"))


EDITABLE_FIELDS = {
    "work_order_number": "WO Number",
    "tds": "TDS",
    "ddtds": "DD TDS Date",
    "account_advance": "Account Advance",
    "mines_qty": "Mines Qty",
    "plant_qty": "Plant Qty",
    "rate": "Rate",
    "cash": "Cash",
    "loading": "Loading",
    "total_advance": "Total Advance",
    "shortage": "Shortage",
    "short_amt": "Short Amt",
    "munsiyana": "Munsiyana",
    "rtgs": "RTGS",
    "account_name": "Account Name",
    "remark": "Remark",
    "status": "Status",
}


@work_order_records_bp.route("/bulk-edit", methods=["GET", "POST"])
@login_required
def bulk_edit():
    mines = Mine.query.order_by(Mine.name).all()
    if request.method == "POST":
        wo_ids = request.form.getlist("wo_ids[]")
        field = request.form.get("field", "")
        value = request.form.get("value", "").strip()
        if not wo_ids or field not in EDITABLE_FIELDS:
            flash("Select work orders and a field", "danger")
            return redirect(url_for("work_order_records.bulk_edit"))
        try:
            for wid in wo_ids:
                wo = WorkOrder.query.get(int(wid))
                if not wo:
                    continue
                if field == "ddtds":
                    wo.ddtds = datetime.strptime(value, "%Y-%m-%d").date() if value else None
                elif field in ("tds", "account_advance", "mines_qty", "plant_qty", "rate", "cash", "loading", "total_advance", "shortage", "short_amt", "munsiyana", "rtgs"):
                    setattr(wo, field, float(value or 0))
                    wo.recalculate()
                elif field in ("work_order_number", "account_name", "remark", "status"):
                    setattr(wo, field, value)
            db.session.commit()
            flash(f"Updated {len(wo_ids)} work order(s)", "success")
            return redirect(url_for("work_order_records.bulk_edit"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for("work_order_records.bulk_edit"))

    query = WorkOrder.query
    mine_id = request.args.get("mine_id", "", type=str)
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    status = request.args.get("status", "")
    if mine_id:
        query = query.filter_by(mine_id=int(mine_id))
    if date_from:
        query = query.filter(WorkOrder.date >= datetime.strptime(date_from, "%Y-%m-%d").date())
    if date_to:
        query = query.filter(WorkOrder.date <= datetime.strptime(date_to, "%Y-%m-%d").date())
    if status:
        query = query.filter(WorkOrder.status == status)
    work_orders = query.order_by(WorkOrder.date.desc()).all()
    return render_template(
        "work_order_records/bulk_edit.html",
        work_orders=work_orders,
        mines=mines,
        editable_fields=EDITABLE_FIELDS,
        mine_id=mine_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
    )


@work_order_records_bp.route("/view/<int:id>")
@login_required
def view(id):
    current_wo = WorkOrder.query.get_or_404(id)
    work_orders = WorkOrder.query.order_by(WorkOrder.date.desc(), WorkOrder.id.desc()).all()

    if request.args.get("export") == "csv":
        headers = ["WO #", "Date", "Truck", "Mine", "Account", "Remark", "TDS", "DD TDS Date", "Acc Adv", "Mines Qty", "Plant Qty", "Rate", "Freight", "Cash", "Loading", "Advance", "Shortage", "Short Amt", "Munsiyana", "RTGS", "Balance", "Status"]
        rows = [
            [
                wo.work_order_number or "",
                wo.date,
                wo.lorry_number,
                wo.mine.name if wo.mine else "",
                wo.account_name or "",
                wo.remark or "",
                float(wo.tds), wo.ddtds.isoformat() if wo.ddtds else "", float(wo.account_advance),
                float(wo.mines_qty) if wo.mines_qty else "",
                float(wo.plant_qty) if wo.plant_qty else "",
                float(wo.rate), float(wo.total_freight),
                float(wo.cash), float(wo.loading), float(wo.total_advance),
                float(wo.shortage) if wo.shortage else "",
                float(wo.short_amt), float(wo.munsiyana), float(wo.rtgs),
                float(wo.balance), wo.status,
            ]
            for wo in work_orders
        ]
        return generate_csv(headers, rows)

    mines = Mine.query.order_by(Mine.name).all()
    mines_json = [{"id": m.id, "name": m.name} for m in mines]
    return render_template("work_order_records/view.html", wo=current_wo, work_orders=work_orders, current_wo=current_wo, mines=mines, mines_json=mines_json)


@work_order_records_bp.route("/autosave/<int:id>", methods=["POST"])
@login_required
def autosave(id):
    wo = WorkOrder.query.get_or_404(id)
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400

    field = data.get("field", "")
    value = data.get("value")

    editable = {
        "date": "date", "lorry_number": "text", "work_order_number": "text",
        "account_name": "text", "remark": "text", "status": "text",
        "tds": "number", "account_advance": "number", "mines_qty": "number",
        "plant_qty": "number", "rate": "number", "cash": "number",
        "loading": "number", "total_advance": "number", "shortage": "number",
        "short_amt": "number", "munsiyana": "number", "rtgs": "number",
        "mine_id": "select", "ddtds": "date",
    }

    if field not in editable:
        return jsonify({"ok": False, "error": f"Field '{field}' not editable"}), 400

    try:
        ftype = editable[field]
        if ftype == "date":
            setattr(wo, field, datetime.strptime(value, "%Y-%m-%d").date() if value else None)
        elif ftype == "number":
            setattr(wo, field, float(value or 0))
        elif ftype == "select":
            setattr(wo, field, int(value) if value else None)
        else:
            setattr(wo, field, str(value).strip() if value else None)

        wo.recalculate()
        db.session.commit()

        return jsonify({
            "ok": True,
            "field": field,
            "value": value,
            "total_freight": float(wo.total_freight or 0),
            "balance": float(wo.balance or 0),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400


@work_order_records_bp.route("/view/<int:id>/add-rows", methods=["POST"])
@login_required
def add_rows(id):
    current_wo = WorkOrder.query.get_or_404(id)
    dates = request.form.getlist("date[]")
    if not dates:
        flash("No rows to add", "danger")
        return redirect(url_for("work_order_records.view", id=id))

    wo_number = current_wo.work_order_number
    if not wo_number:
        wo_number = f"WO-{current_wo.id}"
        current_wo.work_order_number = wo_number

    lorry_numbers = request.form.getlist("lorry_number[]")
    mine_ids = request.form.getlist("mine_id[]")
    tds_list = request.form.getlist("tds[]")
    ddtds_list = request.form.getlist("ddtds[]")
    account_advance_list = request.form.getlist("account_advance[]")
    mines_qty_list = request.form.getlist("mines_qty[]")
    plant_qty_list = request.form.getlist("plant_qty[]")
    rate_list = request.form.getlist("rate[]")
    cash_list = request.form.getlist("cash[]")
    loading_list = request.form.getlist("loading[]")
    total_advance_list = request.form.getlist("total_advance[]")
    shortage_list = request.form.getlist("shortage[]")
    short_amt_list = request.form.getlist("short_amt[]")
    munsiyana_list = request.form.getlist("munsiyana[]")
    rtgs_list = request.form.getlist("rtgs[]")
    account_name_list = request.form.getlist("account_name[]")
    remark_list = request.form.getlist("remark[]")
    petrol_list = request.form.getlist("petrol[]")

    try:
        count = 0
        for i, date_str in enumerate(dates):
            date_str = date_str.strip()
            lorry_number = lorry_numbers[i].strip() if i < len(lorry_numbers) else ""
            if not date_str or not lorry_number:
                continue

            wo = WorkOrder(
                date=datetime.strptime(date_str, "%Y-%m-%d").date(),
                lorry_number=lorry_number,
                work_order_number=wo_number,
                mine_id=int(mine_ids[i]) if i < len(mine_ids) and mine_ids[i] else None,
                tds=float(tds_list[i] or 0) if i < len(tds_list) else 0,
                ddtds=datetime.strptime(ddtds_list[i].strip(), "%Y-%m-%d").date() if i < len(ddtds_list) and ddtds_list[i].strip() else None,
                account_advance=float(account_advance_list[i] or 0) if i < len(account_advance_list) else 0,
                mines_qty=float(mines_qty_list[i] or 0) if i < len(mines_qty_list) else 0,
                plant_qty=float(plant_qty_list[i] or 0) if i < len(plant_qty_list) else 0,
                rate=float(rate_list[i] or 0) if i < len(rate_list) else 0,
                total_freight=0,
                cash=float(cash_list[i] or 0) if i < len(cash_list) else 0,
                loading=float(loading_list[i] or 0) if i < len(loading_list) else 0,
                total_advance=float(total_advance_list[i] or 0) if i < len(total_advance_list) else 0,
                shortage=float(shortage_list[i] or 0) if i < len(shortage_list) else 0,
                short_amt=float(short_amt_list[i] or 0) if i < len(short_amt_list) else 0,
                munsiyana=float(munsiyana_list[i] or 0) if i < len(munsiyana_list) else 0,
                balance=0,
                rtgs=float(rtgs_list[i] or 0) if i < len(rtgs_list) else 0,
                account_name=account_name_list[i].strip() if i < len(account_name_list) else "",
                remark=remark_list[i].strip() if i < len(remark_list) else "",
            )
            wo.recalculate()
            db.session.add(wo)
            db.session.flush()

            petrol_raw = petrol_list[i].strip() if i < len(petrol_list) and petrol_list[i] else ""
            if petrol_raw:
                for part in petrol_raw.split(","):
                    part = part.strip()
                    if ":" in part:
                        pname, pamt = part.rsplit(":", 1)
                        pname = pname.strip()
                        if pname:
                            db.session.add(PetrolStation(work_order_id=wo.id, name=pname, amount=float(pamt or 0)))
                    elif part:
                        db.session.add(PetrolStation(work_order_id=wo.id, name=part, amount=0))

            count += 1

        log_audit("create", "work_order", current_wo.id, f"Added {count} row(s) to WO {wo_number}")
        db.session.commit()
        flash(f"{count} row(s) added successfully", "success")
        return redirect(url_for("work_order_records.view", id=id))
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for("work_order_records.view", id=id))


work_order_fields = [
    ("date", "Date", "date"),
    ("lorry_number", "Truck #", "text"),
    ("work_order_number", "WO Number", "text"),
    ("mine_name", "Mine Name", "text"),
    ("account_name", "Account Name", "text"),
    ("remark", "Remark", "text"),
    ("tds", "TDS", "number"),
    ("ddtds", "DD TDS Date", "date"),
    ("account_advance", "Acc Adv", "number"),
    ("mines_qty", "Mines Qty", "number"),
    ("plant_qty", "Plant Qty", "number"),
    ("rate", "Rate", "number"),
    ("cash", "Cash", "number"),
    ("loading", "Loading", "number"),
    ("total_advance", "Total Advance", "number"),
    ("shortage", "Shortage", "number"),
    ("short_amt", "Short Amt", "number"),
    ("munsiyana", "Munsiyana", "number"),
    ("rtgs", "RTGS", "number"),
    ("petrol", "Petrol (Name:Amt,...)", "text"),
]

@work_order_records_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_work_orders():
    mines = Mine.query.order_by(Mine.name).all()
    wo_id = request.args.get("wo_id", type=int)
    current_wo = WorkOrder.query.get(wo_id) if wo_id else None

    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename.endswith(".csv"):
            flash("Please upload a .csv file", "danger")
            return render_template("work_order_records/import.html", fields=work_order_fields, mines=mines, current_wo=current_wo)

        content = file.stream.read().decode("utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        src_headers = next(reader, [])
        if not src_headers:
            flash("CSV file is empty or has no headers", "danger")
            return render_template("work_order_records/import.html", fields=work_order_fields, mines=mines, current_wo=current_wo)

        all_rows = [r for r in reader]
        preview_rows = all_rows[:5]

        # NEW: get AI mapping suggestions
        groq_api_key = os.environ.get("GROQ_API_KEY")
        ai_mappings = {}
        if groq_api_key and src_headers:
            field_descriptions = ""
            for _, (fkey, flabel, ftype) in enumerate(work_order_fields):
                field_descriptions += f'  "{fkey}" = {flabel} ({ftype})\n'

            sample_rows_text = ""
            for i, row in enumerate(preview_rows):
                sample_rows_text += f"Row {i}: {row}\n"

            prompt = f"""The user uploaded a CSV with these headers: {', '.join(src_headers)}

Here are sample rows from the CSV:
{sample_rows_text}

Available work order fields (use the exact key):
{field_descriptions}

Map each CSV column (by its header name and sample data) to the correct work order field key.
Return a JSON object where keys are column indices as strings ("0", "1", etc.) and values are the EXACT field key from the list above (like "date", "lorry_number", "mine_name", etc.).
Only include columns with high confidence.
Return ONLY the JSON object, no other text.
"""

            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "openai/gpt-oss-120b",
                        "messages": [
                            {"role": "system", "content": "You are a helpful assistant that maps CSV column indices to work order field names."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.0,
                    },
                    timeout=15,
                )

                if response.status_code == 200:
                    result = response.json()
                    choice = result.get("choices", [{}])[0]
                    message = choice.get("message", {})
                    content = message.get("content", "").strip()
                    import traceback
                    print(f"[AI DEBUG] Raw content: {content}")
                    mapping = json.loads(content)
                    print(f"[AI DEBUG] Parsed mapping: {mapping}")
                    valid_keys = {fkey for fkey, _, _ in work_order_fields}
                    if isinstance(mapping, dict):
                        high_conf = {str(k): v for k, v in mapping.items() if v and str(v) in valid_keys}
                        ai_mappings = high_conf
                        print(f"[AI DEBUG] Final ai_mappings: {ai_mappings}")
            except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"[AI DEBUG] Error: {e}")
                ai_mappings = {}

        return render_template(
            "work_order_records/import.html",
            fields=work_order_fields,
            mines=mines,
            ai_mappings=ai_mappings,
            src_headers=src_headers,
            preview_rows=preview_rows,
            total_rows=len(all_rows),
            raw_data=[src_headers] + all_rows,
            current_wo=current_wo,
        )
    return render_template("work_order_records/import.html", fields=work_order_fields, mines=mines, current_wo=current_wo)


@work_order_records_bp.route("/import/execute", methods=["POST"])
@login_required
def import_execute():
    wo_id = request.form.get("wo_id", type=int)
    current_wo = WorkOrder.query.get(wo_id) if wo_id else None
    if current_wo and not current_wo.work_order_number:
        current_wo.work_order_number = f"WO-{current_wo.id}"
    mapping = {}
    for key in request.form:
        if key.startswith("map_"):
            src_col = int(key[4:])
            dst_field = request.form[key]
            if dst_field:
                mapping[src_col] = dst_field

    if not mapping:
        flash("No field mapping provided", "danger")
        return redirect(url_for("work_order_records.import_work_orders"))

    data_keys = [k for k in request.form if k.startswith("data_")]
    row_indices = set()
    for k in data_keys:
        parts = k.split("_")
        if len(parts) >= 3:
            row_indices.add(int(parts[1]))
    sorted_rows = sorted(row_indices)
    count = 0
    try:
        for i in sorted_rows:
            date_str = request.form.get(f"data_{i}_0", "").strip()
            lorry_number = request.form.get(f"data_{i}_1", "").strip()
            if not date_str or not lorry_number:
                continue

            data = {}
            for src_col, dst_field in mapping.items():
                val = request.form.get(f"data_{i}_{src_col}", "").strip()
                data[dst_field] = val

            mine_id = None
            if current_wo and current_wo.mine_id:
                mine_id = current_wo.mine_id
            elif "mine_name" in data and data["mine_name"]:
                mine = Mine.query.filter_by(name=data["mine_name"]).first()
                if not mine:
                    mine = Mine(name=data["mine_name"])
                    db.session.add(mine)
                    db.session.flush()
                mine_id = mine.id

            wo = WorkOrder(
                date=datetime.strptime(data.get("date", date_str), "%Y-%m-%d").date(),
                lorry_number=data.get("lorry_number", lorry_number),
                work_order_number=current_wo.work_order_number if current_wo else (data.get("work_order_number", None) or None),
                mine_id=mine_id,
                tds=float(data.get("tds", 0) or 0),
                ddtds=datetime.strptime(data["ddtds"], "%Y-%m-%d").date() if data.get("ddtds", "").strip() else None,
                account_advance=float(data.get("account_advance", 0) or 0),
                mines_qty=float(data.get("mines_qty", 0) or 0),
                plant_qty=float(data.get("plant_qty", 0) or 0),
                rate=float(data.get("rate", 0) or 0),
                total_freight=0,
                cash=float(data.get("cash", 0) or 0),
                loading=float(data.get("loading", 0) or 0),
                total_advance=float(data.get("total_advance", 0) or 0),
                shortage=float(data.get("shortage", 0) or 0),
                short_amt=float(data.get("short_amt", 0) or 0),
                munsiyana=float(data.get("munsiyana", 0) or 0),
                balance=0,
                rtgs=float(data.get("rtgs", 0) or 0),
                account_name=data.get("account_name", ""),
                remark=data.get("remark", ""),
            )
            wo.recalculate()
            db.session.add(wo)
            db.session.flush()

            petrol_raw = data.get("petrol", "")
            if petrol_raw:
                for part in petrol_raw.split(","):
                    part = part.strip()
                    if ":" in part:
                        pname, pamt = part.rsplit(":", 1)
                        pname = pname.strip()
                        if pname:
                            db.session.add(PetrolStation(work_order_id=wo.id, name=pname, amount=float(pamt or 0)))
                    elif part:
                        db.session.add(PetrolStation(work_order_id=wo.id, name=part, amount=0))

            count += 1

        log_audit("import", "work_order", 0, f"Imported {count} work order(s)")
        db.session.commit()
        flash(f"{count} work order(s) imported successfully", "success")
        return redirect(url_for("work_order_records.work_orders"))
    except Exception as e:
        db.session.rollback()
        flash(f"Import error: {str(e)}", "danger")
        return redirect(url_for("work_order_records.import_work_orders"))


@work_order_records_bp.route("/daily-payments")
@login_required
def daily_payments():
    today = datetime.today().strftime("%Y-%m-%d")
    date_from = request.args.get("date_from", today)
    date_to = request.args.get("date_to", today)

    query = WorkOrder.query.filter(
        db.or_(
            WorkOrder.cash > 0,
            WorkOrder.total_advance > 0,
            WorkOrder.rtgs > 0,
            WorkOrder.account_advance > 0,
            WorkOrder.total_freight > 0,
        )
    )

    if date_from:
        query = query.filter(WorkOrder.date >= datetime.strptime(date_from, "%Y-%m-%d").date())
    if date_to:
        query = query.filter(WorkOrder.date <= datetime.strptime(date_to, "%Y-%m-%d").date())

    rows = query.options(
        db.joinedload(WorkOrder.mine),
        db.joinedload(WorkOrder.petrol_stations),
    ).order_by(WorkOrder.date.desc(), WorkOrder.id).all()

    daily_groups = {}
    grand_freight = grand_cash = grand_loading = grand_advance = 0
    grand_shortage = grand_short_amt = grand_munsiyana = 0
    grand_tds = grand_acc_adv = grand_rtgs = 0
    grand_petrol = grand_deductions = grand_net = 0

    for wo in rows:
        d = wo.date.isoformat()
        if d not in daily_groups:
            daily_groups[d] = []

        freight = float(wo.total_freight or 0)
        cash = float(wo.cash or 0)
        loading = float(wo.loading or 0)
        advance = float(wo.total_advance or 0)
        shortage = float(wo.shortage or 0)
        short_amt = float(wo.short_amt or 0)
        munsiyana = float(wo.munsiyana or 0)
        tds = float(wo.tds or 0)
        acc_adv = float(wo.account_advance or 0)
        rtgs = float(wo.rtgs or 0)
        petrol = sum(float(p.amount or 0) for p in wo.petrol_stations)

        deductions = cash + loading + advance + shortage + short_amt + munsiyana + tds + acc_adv + petrol
        net = freight - deductions

        daily_groups[d].append({
            "id": wo.id,
            "lorry_number": wo.lorry_number,
            "work_order_number": wo.work_order_number or "",
            "account_name": wo.account_name or "-",
            "mine_name": wo.mine.name if wo.mine else "-",
            "ddtds": wo.ddtds.isoformat() if wo.ddtds else None,
            "freight": freight,
            "cash": cash,
            "loading": loading,
            "advance": advance,
            "shortage": shortage,
            "short_amt": short_amt,
            "munsiyana": munsiyana,
            "tds": tds,
            "account_advance": acc_adv,
            "petrol": petrol,
            "deductions": deductions,
            "rtgs": rtgs,
            "net": round(net, 2),
        })
        grand_freight += freight
        grand_cash += cash
        grand_loading += loading
        grand_advance += advance
        grand_shortage += shortage
        grand_short_amt += short_amt
        grand_munsiyana += munsiyana
        grand_tds += tds
        grand_acc_adv += acc_adv
        grand_petrol += petrol
        grand_deductions += deductions
        grand_rtgs += rtgs
        grand_net += net

    sorted_dates = sorted(daily_groups.keys(), reverse=True)
    return render_template(
        "work_order_records/daily_payments.html",
        daily_groups=daily_groups,
        sorted_dates=sorted_dates,
        date_from=date_from,
        date_to=date_to,
        grand_freight=round(grand_freight, 2),
        grand_cash=round(grand_cash, 2),
        grand_loading=round(grand_loading, 2),
        grand_advance=round(grand_advance, 2),
        grand_shortage=round(grand_shortage, 2),
        grand_short_amt=round(grand_short_amt, 2),
        grand_munsiyana=round(grand_munsiyana, 2),
        grand_tds=round(grand_tds, 2),
        grand_account_advance=round(grand_acc_adv, 2),
        grand_petrol=round(grand_petrol, 2),
        grand_deductions=round(grand_deductions, 2),
        grand_rtgs=round(grand_rtgs, 2),
        grand_net=round(grand_net, 2),
        mines=Mine.query.order_by(Mine.name).all(),
    )


@work_order_records_bp.route("/daily-payments/add", methods=["POST"])
@login_required
def add_daily_payment():
    try:
        date_str = request.form.get("date", "").strip()
        lorry_number = request.form.get("lorry_number", "").strip()
        if not date_str or not lorry_number:
            flash("Date and Lorry Number are required", "danger")
            return redirect(url_for("work_order_records.daily_payments"))

        wo = WorkOrder(
            date=datetime.strptime(date_str, "%Y-%m-%d").date(),
            lorry_number=lorry_number,
            work_order_number=None,
            mine_id=int(request.form.get("mine_id")) if request.form.get("mine_id") else None,
            account_name=request.form.get("account_name", "").strip(),
            remark=request.form.get("remark", "").strip(),
            total_freight=float(request.form.get("total_freight", 0) or 0),
            cash=float(request.form.get("cash", 0) or 0),
            loading=float(request.form.get("loading", 0) or 0),
            total_advance=float(request.form.get("total_advance", 0) or 0),
            shortage=float(request.form.get("shortage", 0) or 0),
            short_amt=float(request.form.get("short_amt", 0) or 0),
            munsiyana=float(request.form.get("munsiyana", 0) or 0),
            tds=float(request.form.get("tds", 0) or 0),
            ddtds=datetime.strptime(request.form.get("ddtds", "").strip(), "%Y-%m-%d").date() if request.form.get("ddtds", "").strip() else None,
            account_advance=float(request.form.get("account_advance", 0) or 0),
            rtgs=float(request.form.get("rtgs", 0) or 0),
            mines_qty=0,
            plant_qty=0,
            rate=0,
            balance=0,
        )
        wo.recalculate()
        db.session.add(wo)
        db.session.flush()

        petrol_amt = float(request.form.get("petrol", 0) or 0)
        petrol_name = request.form.get("petrol_name", "").strip()
        if petrol_amt > 0 and petrol_name:
            ps = PetrolStation(work_order_id=wo.id, name=petrol_name, amount=petrol_amt)
            db.session.add(ps)

        log_audit("create", "work_order", wo.id, f"Added daily payment for {lorry_number}")
        db.session.commit()
        flash("Payment added successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error adding payment: {str(e)}", "danger")
    return redirect(url_for("work_order_records.daily_payments"))


@work_order_records_bp.route("/ai-search", methods=["POST"])
@login_required
def ai_search():
    data = request.get_json()
    query_text = data.get("query", "").strip() if data else ""
    if not query_text:
        return jsonify({"results": [], "query": ""})

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        return jsonify({"results": [], "query": query_text, "error": "AI not configured"})

    field_names = [
        "date", "date_from", "date_to", "lorry_number", "work_order_number",
        "mine_name", "account_name", "status", "mines_qty", "plant_qty",
        "rate", "total_freight", "cash", "loading", "total_advance",
        "rtgs", "balance", "tds", "remark"
    ]

    prompt = f"""You are a search filter generator for a transport management system.

The user types a natural language query. Convert it to a JSON filter object.

Available filter fields:
- date_from (YYYY-MM-DD), date_to (YYYY-MM-DD)
- lorry_number (truck number, partial match OK)
- work_order_number
- mine_name (partial match OK)
- account_name (partial match OK)
- status ("Pending" or "Completed")
- min_freight, max_freight (number)
- min_balance, max_balance (number)
- has_rtgs (true/false)

User query: "{query_text}"

Return ONLY a JSON object with the filter fields. Example:
{{"lorry_number": "TRK-01", "status": "Pending"}}

If the query is unclear, return an empty object {{}}.
Do NOT include any explanation, just the JSON."""

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-oss-120b",
                "messages": [
                    {"role": "system", "content": "You convert natural language queries into JSON filter objects for a transport database. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
            },
            timeout=10,
        )

        if response.status_code != 200:
            return jsonify({"results": [], "query": query_text, "error": "AI service error"})

        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        filters = json.loads(content)
    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError):
        return jsonify({"results": [], "query": query_text, "error": "Could not understand query"})

    query = WorkOrder.query

    if filters.get("date_from"):
        try:
            d = datetime.strptime(filters["date_from"], "%Y-%m-%d").date()
            query = query.filter(WorkOrder.date >= d)
        except ValueError:
            pass
    if filters.get("date_to"):
        try:
            d = datetime.strptime(filters["date_to"], "%Y-%m-%d").date()
            query = query.filter(WorkOrder.date <= d)
        except ValueError:
            pass
    if filters.get("lorry_number"):
        query = query.filter(WorkOrder.lorry_number.ilike(f"%{filters['lorry_number']}%"))
    if filters.get("work_order_number"):
        query = query.filter(WorkOrder.work_order_number.ilike(f"%{filters['work_order_number']}%"))
    if filters.get("mine_name"):
        query = query.join(Mine, WorkOrder.mine_id == Mine.id, isouter=True).filter(Mine.name.ilike(f"%{filters['mine_name']}%"))
    if filters.get("account_name"):
        query = query.filter(WorkOrder.account_name.ilike(f"%{filters['account_name']}%"))
    if filters.get("status"):
        query = query.filter(WorkOrder.status == filters["status"])
    if filters.get("min_freight"):
        try:
            query = query.filter(WorkOrder.total_freight >= float(filters["min_freight"]))
        except (ValueError, TypeError):
            pass
    if filters.get("max_freight"):
        try:
            query = query.filter(WorkOrder.total_freight <= float(filters["max_freight"]))
        except (ValueError, TypeError):
            pass
    if filters.get("min_balance"):
        try:
            query = query.filter(WorkOrder.balance >= float(filters["min_balance"]))
        except (ValueError, TypeError):
            pass
    if filters.get("max_balance"):
        try:
            query = query.filter(WorkOrder.balance <= float(filters["max_balance"]))
        except (ValueError, TypeError):
            pass
    if filters.get("has_rtgs"):
        query = query.filter(WorkOrder.rtgs > 0)

    results = query.options(
        db.joinedload(WorkOrder.mine)
    ).order_by(WorkOrder.date.desc()).limit(50).all()

    results_data = []
    for wo in results:
        results_data.append({
            "id": wo.id,
            "date": wo.date.isoformat() if wo.date else None,
            "lorry_number": wo.lorry_number or "",
            "work_order_number": wo.work_order_number or "",
            "mine_name": wo.mine.name if wo.mine else "",
            "account_name": wo.account_name or "",
            "total_freight": float(wo.total_freight or 0),
            "balance": float(wo.balance or 0),
            "status": wo.status or "",
            "rate": float(wo.rate or 0),
            "cash": float(wo.cash or 0),
            "rtgs": float(wo.rtgs or 0),
        })

    return jsonify({
        "results": results_data,
        "filters": filters,
        "query": query_text,
        "count": len(results_data),
    })


@work_order_records_bp.route("/ai-map", methods=["POST"])
@login_required
def ai_map():
    data = request.get_json()
    if not data:
        return jsonify({})

    headers = data.get("headers", [])
    sample_rows = data.get("sampleRows", [])

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        return jsonify({})

    # Build field descriptions prompt
    field_descriptions = "Work order CSV columns and their meanings:\n"
    for col_idx, (_, label, _) in enumerate(work_order_fields):
        field_descriptions += f"{col_idx}: {label}\n"

    # Add sample rows context
    if sample_rows:
        field_descriptions += "\nSample data rows:\n"
        for i, row in enumerate(sample_rows[:5]):
            field_descriptions += f"Row {i}: {row}\n"

    prompt = f"""{field_descriptions}

Based on the headers and sample rows above, map each column index to the corresponding work order field name.
Return a JSON object mapping column index (string) to field name (string).
Only include columns with high confidence (>=0.7 matching).
If unsure, omit the column.
Return ONLY the JSON object, no other text.
"""

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-oss-120b",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant that maps CSV column indices to work order field names."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
            },
            timeout=15,
        )

        if response.status_code != 200:
            return jsonify({})

        result = response.json()
        choice = result.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "").strip()

        # Parse JSON from content
        mapping = json.loads(content)
        if isinstance(mapping, dict):
            # Filter to high-confidence mappings only (keys are strings, values are field names)
            high_conf = {k: v for k, v in mapping.items() if isinstance(k, str) and v}
            return jsonify(high_conf)

        return jsonify({})
    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError):
        return jsonify({})

