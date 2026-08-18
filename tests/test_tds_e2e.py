"""End-to-end tests for TDS auto-calculation via routes."""
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.models import WorkOrder, Transporter, Mine, Plant, User


@pytest.fixture
def seed(app):
    """Create plant, mine, and transporter for tests."""
    plant = Plant(name="Test Plant")
    db.session.add(plant)
    db.session.flush()

    mine = Mine(name="Test Mine", plant_id=plant.id)
    db.session.add(mine)
    db.session.flush()

    transporter = Transporter(name="Test Transporter", tds_rate=Decimal("2.0"))
    db.session.add(transporter)
    db.session.flush()

    return {"plant": plant, "mine": mine, "transporter": transporter}


@pytest.fixture
def auth_client(client):
    """Login and return authenticated client."""
    login(client)
    return client


def login(client, username="admin", password="admin123"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


class TestTransporterTdsRatePersist:
    def test_transporter_tds_rate_persist(self, app, auth_client, seed):
        """Transporter tds_rate persists after update."""
        tid = seed["transporter"].id

        resp = auth_client.get(f"/transporters/edit/{tid}")
        assert resp.status_code == 200

        seed["transporter"].tds_rate = Decimal("3.5")
        db.session.commit()

        t = Transporter.query.get(tid)
        assert float(t.tds_rate) == 3.5


class TestAutosaveExemptPeriod:
    def test_autosave_exempt_period(self, app, auth_client, seed):
        """WO created via save-new + autosave with exempt date → TDS = 0."""
        resp = auth_client.post("/work-orders/save-new", json=[{
            "date": "2026-06-15",
            "lorry_number": "HR01",
            "mine_id": str(seed["mine"].id),
            "mines_qty": "100",
            "rate": "50",
        }])
        assert resp.status_code == 200
        wo_id = resp.get_json()["ids"][0]

        wo = WorkOrder.query.get(wo_id)
        wo.transporter_id = seed["transporter"].id
        db.session.commit()

        resp = auth_client.post(f"/work-orders/autosave/{wo_id}", json={
            "wo_id": wo_id,
            "field": "date",
            "value": "2026-06-15",
        })
        data = resp.get_json()
        assert data["ok"] is True
        assert float(data["tds"]) == 0.0


class TestAutosaveNonExemptPeriod:
    def test_autosave_non_exempt_period(self, app, auth_client, seed):
        """WO with non-exempt date → TDS = freight × rate%."""
        resp = auth_client.post("/work-orders/save-new", json=[{
            "date": "2023-06-15",
            "lorry_number": "HR02",
            "mine_id": str(seed["mine"].id),
            "mines_qty": "100",
            "rate": "50",
        }])
        assert resp.status_code == 200
        wo_id = resp.get_json()["ids"][0]

        wo = WorkOrder.query.get(wo_id)
        wo.transporter_id = seed["transporter"].id
        db.session.commit()

        resp = auth_client.post(f"/work-orders/autosave/{wo_id}", json={
            "wo_id": wo_id,
            "field": "rate",
            "value": "50",
        })
        data = resp.get_json()
        assert data["ok"] is True
        assert float(data["tds"]) == 100.0  # 5000 * 2%


class TestAutosaveManualOverride:
    def test_autosave_manual_override(self, app, auth_client, seed):
        """Setting TDS via autosave with field=tds → tds_auto=False."""
        resp = auth_client.post("/work-orders/save-new", json=[{
            "date": "2023-06-15",
            "lorry_number": "HR03",
            "mine_id": str(seed["mine"].id),
            "mines_qty": "100",
            "rate": "50",
        }])
        assert resp.status_code == 200
        wo_id = resp.get_json()["ids"][0]

        wo = WorkOrder.query.get(wo_id)
        wo.transporter_id = seed["transporter"].id
        db.session.commit()

        resp = auth_client.post(f"/work-orders/autosave/{wo_id}", json={
            "wo_id": wo_id,
            "field": "tds",
            "value": "250",
        })
        data = resp.get_json()
        assert data["ok"] is True
        assert float(data["tds"]) == 250.0

        wo = WorkOrder.query.get(wo_id)
        assert wo.tds_auto is False


class TestAutosaveRecalculateOnDateChange:
    def test_autosave_recalculate_on_date_change(self, app, auth_client, seed):
        """Start exempt (TDS=0), change date to non-exempt → TDS recalculates."""
        resp = auth_client.post("/work-orders/save-new", json=[{
            "date": "2026-06-15",
            "lorry_number": "HR04",
            "mine_id": str(seed["mine"].id),
            "mines_qty": "100",
            "rate": "50",
        }])
        assert resp.status_code == 200
        wo_id = resp.get_json()["ids"][0]

        wo = WorkOrder.query.get(wo_id)
        wo.transporter_id = seed["transporter"].id
        db.session.commit()

        resp = auth_client.post(f"/work-orders/autosave/{wo_id}", json={
            "wo_id": wo_id,
            "field": "date",
            "value": "2026-06-15",
        })
        assert float(resp.get_json()["tds"]) == 0.0

        resp = auth_client.post(f"/work-orders/autosave/{wo_id}", json={
            "wo_id": wo_id,
            "field": "date",
            "value": "2023-06-15",
        })
        data = resp.get_json()
        assert data["ok"] is True
        assert float(data["tds"]) == 100.0


class TestBalanceCalculation:
    def test_balance_calculation(self, app, auth_client, seed):
        """balance = freight - (advance + short_amt + munsiyana + rtgs + tds + account_advance)."""
        resp = auth_client.post("/work-orders/save-new", json=[{
            "date": "2023-06-15",
            "lorry_number": "HR05",
            "mine_id": str(seed["mine"].id),
            "mines_qty": "100",
            "rate": "50",
        }])
        assert resp.status_code == 200
        wo_id = resp.get_json()["ids"][0]

        wo = WorkOrder.query.get(wo_id)
        wo.transporter_id = seed["transporter"].id
        db.session.commit()

        auth_client.post(f"/work-orders/autosave/{wo_id}", json={
            "wo_id": wo_id, "field": "short_amt", "value": "200",
        })
        auth_client.post(f"/work-orders/autosave/{wo_id}", json={
            "wo_id": wo_id, "field": "munsiyana", "value": "300",
        })
        auth_client.post(f"/work-orders/autosave/{wo_id}", json={
            "wo_id": wo_id, "field": "rtgs", "value": "500",
        })
        auth_client.post(f"/work-orders/autosave/{wo_id}", json={
            "wo_id": wo_id, "field": "account_advance", "value": "1000",
        })

        wo = WorkOrder.query.get(wo_id)
        freight = float(wo.mines_qty) * float(wo.rate)  # 5000
        deductions = (
            float(wo.total_advance)
            + float(wo.short_amt)
            + float(wo.munsiyana)
            + float(wo.rtgs)
            + float(wo.tds)
            + float(wo.account_advance)
        )
        expected_balance = round(freight - deductions, 2)
        assert float(wo.balance) == expected_balance


class TestSaveRouteTdsFlow:
    def test_save_route_tds_flow(self, app, auth_client, seed):
        """Full save route with freight and TDS auto-calculation."""
        resp = auth_client.post("/work-orders/save-new", json=[{
            "date": "2023-06-15",
            "lorry_number": "HR06",
            "mine_id": str(seed["mine"].id),
            "mines_qty": "100",
            "rate": "50",
        }])
        assert resp.status_code == 200
        wo_id = resp.get_json()["ids"][0]

        wo = WorkOrder.query.get(wo_id)
        wo.transporter_id = seed["transporter"].id
        db.session.commit()

        resp = auth_client.post(f"/work-orders/save/{wo_id}", json={
            "mines_qty": 100,
            "rate": 50,
        })
        data = resp.get_json()
        assert data["ok"] is True
        assert float(data["tds"]) == 100.0
        assert float(data["total_freight"]) == 5000.0
