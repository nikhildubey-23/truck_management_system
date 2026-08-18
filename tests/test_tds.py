"""Tests for TDS auto-calculation."""
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.models import WorkOrder, Transporter, Mine, Plant, calculate_tds


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


def test_tds_exempt_within_period(app, seed):
    """TDS should be 0 when trip date is within exemption period."""
    wo = WorkOrder(
        date=date(2026, 6, 15),  # Within FY 2026-27 exemption
        lorry_number="HR01",
        mine_id=seed["mine"].id,
        mines_qty=100,
        rate=50,
    )
    db.session.add(wo)
    db.session.flush()

    tds = calculate_tds(wo, seed["transporter"])
    assert tds == 0


def test_tds_calculated_outside_period(app, seed):
    """TDS should be calculated when trip date is outside exemption period."""
    wo = WorkOrder(
        date=date(2023, 6, 15),  # Outside all exemption periods
        lorry_number="HR01",
        mine_id=seed["mine"].id,
        mines_qty=100,
        rate=50,
    )
    db.session.add(wo)
    db.session.flush()

    wo.recalculate()

    tds = calculate_tds(wo, seed["transporter"])
    assert tds == 100.0  # 5000 * 2% = 100


def test_tds_no_transporter_rate(app, seed):
    """TDS should be 0 if transporter has no rate."""
    no_rate_transporter = Transporter(name="No Rate Transporter", tds_rate=0)
    db.session.add(no_rate_transporter)
    db.session.flush()

    wo = WorkOrder(
        date=date(2023, 6, 15),
        lorry_number="HR01",
        mine_id=seed["mine"].id,
        mines_qty=100,
        rate=50,
    )
    db.session.add(wo)
    db.session.flush()

    tds = calculate_tds(wo, no_rate_transporter)
    assert tds == 0


def test_recalculate_auto_tds(app, seed):
    """recalculate() should auto-calc TDS when tds_auto=True."""
    wo = WorkOrder(
        date=date(2023, 6, 15),
        lorry_number="HR01",
        mine_id=seed["mine"].id,
        transporter_id=seed["transporter"].id,
        mines_qty=100,
        rate=50,
        tds_auto=True,
    )
    db.session.add(wo)
    db.session.flush()

    wo.recalculate()
    db.session.commit()

    assert float(wo.tds) == 100.0


def test_recalculate_manual_override(app, seed):
    """recalculate() should NOT auto-calc TDS when tds_auto=False."""
    wo = WorkOrder(
        date=date(2023, 6, 15),
        lorry_number="HR01",
        mine_id=seed["mine"].id,
        transporter_id=seed["transporter"].id,
        mines_qty=100,
        rate=50,
        tds=500,  # Manual override
        tds_auto=False,
    )
    db.session.add(wo)
    db.session.flush()

    wo.recalculate()
    db.session.commit()

    assert float(wo.tds) == 500  # Should keep manual value
