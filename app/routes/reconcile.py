import csv, io, os, json
import requests
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
from app import db
from app.models import WorkOrder, Mine

reconcile_bp = Blueprint("reconcile", __name__, url_prefix="/reconcile")


def parse_bank_csv(file_content):
    rows = []
    try:
        reader = csv.DictReader(io.StringIO(file_content))
        for row in reader:
            rows.append({k.strip(): v.strip() if v else "" for k, v in row.items()})
    except Exception:
        return []

    cleaned = []
    for row in rows:
        credit = 0
        debit = 0
        amount = 0
        for key in row:
            kl = key.lower()
            val = row[key].replace(",", "").replace("₹", "").replace("Dr", "").replace("Cr", "").strip()
            try:
                num = float(val) if val else 0
            except ValueError:
                num = 0
            if "credit" in kl or "cr" == kl:
                credit = num
            elif "debit" in kl or "dr" == kl:
                debit = num
            elif "amount" in kl:
                amount = num

        narration = ""
        for key in row:
            kl = key.lower()
            if "narr" in kl or "desc" in kl or "particular" in kl or "remark" in kl:
                narration = row[key]
                break

        date_val = ""
        for key in row:
            kl = key.lower()
            if "date" in kl or "txn" in kl:
                date_val = row[key]
                break

        credit_amount = credit if credit > 0 else amount

        if credit_amount > 0 or debit > 0:
            cleaned.append({
                "date": date_val,
                "narration": narration,
                "debit": debit,
                "credit": credit_amount,
                "raw": row,
            })

    return cleaned


def ai_match_bank_entries(bank_entries, pending_wos):
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        return []

    bank_summary = []
    for i, entry in enumerate(bank_entries[:30]):
        bank_summary.append(f"Bank #{i}: Date={entry['date']}, Credit=₹{entry['credit']}, Debit=₹{entry['debit']}, Narration={entry['narration'][:80]}")

    wo_summary = []
    for wo in pending_wos[:50]:
        wo_summary.append(f"WO#{wo.id}: Truck={wo.lorry_number}, Date={wo.date}, Mine={wo.mine.name if wo.mine else 'N/A'}, Balance=₹{wo.balance}, RTGS=₹{wo.rtgs}, Account={wo.account_name or 'N/A'}")

    prompt = f"""Match bank transaction entries to pending work order payments.

Bank entries (credit = money received):
{chr(10).join(bank_summary)}

Pending Work Orders (balance > 0):
{chr(10).join(wo_summary)}

For each bank entry, find the best matching work order based on:
- Amount match (RTGS/balance amount)
- Truck number mentioned in narration
- Account name match
- Date proximity

Return a JSON array of matches:
[{{"bank_idx": 0, "wo_id": 25, "confidence": 0.9, "reason": "RTGS ₹53000 matches WO balance"}}]

Only include matches with confidence >= 0.5.
Return ONLY the JSON array, no other text."""

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
                    {"role": "system", "content": "You are a bank reconciliation assistant. Match bank transactions to work order payments. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
            },
            timeout=20,
        )

        if response.status_code != 200:
            return []

        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        matches = json.loads(content)
        return matches if isinstance(matches, list) else []
    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError):
        return []


@reconcile_bp.route("/")
@login_required
def upload_form():
    return render_template("reconcile/upload.html")


@reconcile_bp.route("/preview", methods=["POST"])
@login_required
def preview():
    file = request.files.get("bank_file")
    if not file or not file.filename:
        flash("Please upload a bank CSV file", "danger")
        return redirect(url_for("reconcile.upload_form"))

    content = file.read().decode("utf-8-sig", errors="replace")
    bank_entries = parse_bank_csv(content)

    if not bank_entries:
        flash("Could not parse bank CSV. Check format.", "danger")
        return redirect(url_for("reconcile.upload_form"))

    credit_entries = [e for e in bank_entries if e["credit"] > 0]

    pending_wos = WorkOrder.query.filter(
        WorkOrder.balance > 0
    ).options(
        db.joinedload(WorkOrder.mine)
    ).order_by(WorkOrder.date.desc()).limit(100).all()

    matches = ai_match_bank_entries(credit_entries, pending_wos)

    wo_map = {wo.id: wo for wo in pending_wos}

    results = []
    for m in matches:
        bank_idx = m.get("bank_idx", -1)
        wo_id = m.get("wo_id", 0)
        confidence = m.get("confidence", 0)
        reason = m.get("reason", "")

        if 0 <= bank_idx < len(credit_entries) and wo_id in wo_map:
            entry = credit_entries[bank_idx]
            wo = wo_map[wo_id]
            results.append({
                "bank_date": entry["date"],
                "bank_narration": entry["narration"][:100],
                "bank_amount": entry["credit"],
                "wo_id": wo.id,
                "wo_truck": wo.lorry_number,
                "wo_date": str(wo.date),
                "wo_mine": wo.mine.name if wo.mine else "N/A",
                "wo_balance": float(wo.balance or 0),
                "wo_account": wo.account_name or "",
                "confidence": confidence,
                "reason": reason,
            })

    unmatched_banks = []
    matched_bank_indices = {m.get("bank_idx") for m in matches}
    for i, entry in enumerate(credit_entries):
        if i not in matched_bank_indices:
            unmatched_banks.append(entry)

    session["reconcile_results"] = results
    session["reconcile_unmatched"] = unmatched_banks

    return render_template(
        "reconcile/results.html",
        results=results,
        unmatched_banks=unmatched_banks,
        total_entries=len(credit_entries),
        matched_count=len(results),
    )


@reconcile_bp.route("/confirm", methods=["POST"])
@login_required
def confirm():
    confirmed_ids = request.form.getlist("confirmed")
    results = session.get("reconcile_results", [])

    matched_results = [r for r in results if f"bank_{results.index(r)}" in confirmed_ids]

    updated = 0
    for match in matched_results:
        wo = WorkOrder.query.get(match["wo_id"])
        if not wo:
            continue
        bank_amount = match["bank_amount"]
        wo_balance = float(wo.balance or 0)

        wo.rtgs = float(wo.rtgs or 0) + bank_amount
        wo.balance = max(0, wo_balance - bank_amount)

        if wo.balance <= 0:
            wo.status = "Completed"

        updated += 1

    db.session.commit()

    session.pop("reconcile_results", None)
    session.pop("reconcile_unmatched", None)

    flash(f"Reconciled {updated} work order(s) successfully", "success")
    return redirect(url_for("reconcile.upload_form"))
