from datetime import date, datetime

import pandas as pd

from core.cable.forecast import BASIS_RATIO, BASIS_ROUTE, BASIS_SOLL, forecast
from core.cable.report import daily_report_text, parse_date

MAP = {"cable_id": "Kabel", "cross_section": "QS", "target_length": "Soll", "pulled_length": "Ist",
       "date": "Datum", "target1": "Z1", "target2": "Z2"}


def frame():
    return pd.DataFrame([
        # gleiche Strecke A-B, 3x1,5: zwei gezogen (10 und 12), ein offenes mit Soll 8 -> Prognose 11
        {"Kabel": "a", "QS": "3x1,5", "Soll": 8, "Ist": 10, "Datum": "21.10.26", "Z1": "A", "Z2": "B"},
        {"Kabel": "b", "QS": "3x1,5", "Soll": 8, "Ist": 12, "Datum": "21.10.26", "Z1": "B", "Z2": "A"},
        {"Kabel": "c", "QS": "3x1,5", "Soll": 8, "Ist": None, "Datum": None, "Z1": "A", "Z2": "B"},
        # andere Strecke, gleicher Querschnitt: Faktor Ist/Soll (22/16 = 1,375) -> 20 * 1,375
        {"Kabel": "d", "QS": "3x1,5", "Soll": 20, "Ist": None, "Datum": None, "Z1": "C", "Z2": "D"},
        # anderer Querschnitt ohne Vergleich -> Soll
        {"Kabel": "e", "QS": "5x2,5", "Soll": 30, "Ist": None, "Datum": None, "Z1": "A", "Z2": "B"},
        {"Kabel": "f", "QS": "5x2,5", "Soll": 5, "Ist": 6, "Datum": "22.10.26", "Z1": "X", "Z2": "Y"},
    ])


def test_forecast_uses_route_then_ratio_then_soll():
    result = forecast(frame(), MAP)
    rows = list(result.rows.values())
    assert (rows[2].basis, rows[2].length) == (BASIS_ROUTE, 11.0)
    assert (rows[3].basis, rows[3].length) == (BASIS_RATIO, 27.5)
    assert (rows[4].basis, rows[4].length) == (BASIS_RATIO, 36.0)  # 5x2,5: 6/5 = 1,2 * 30
    only = forecast(frame().iloc[[4]], MAP)
    assert list(only.rows.values())[0].basis == BASIS_SOLL


def test_forecast_totals():
    result = forecast(frame(), MAP)
    s = {x.label: x for x in result.sections}["3x1,5"]
    assert (s.total, s.done, s.open) == (4, 2, 2)
    assert s.planned_m == 44 and s.done_m == 22 and s.predicted_open_m == 38.5
    assert s.forecast_m == 60.5 and round(s.delta_m, 2) == 16.5
    assert result.total.total == 6


def test_forecast_uses_only_first_three_references():
    rows = [{"Kabel": str(i), "QS": "q", "Soll": 10, "Ist": v, "Datum": f"0{i + 1}.10.26", "Z1": "A", "Z2": "B"}
            for i, v in enumerate([10, 10, 10, 40])]
    rows.append({"Kabel": "x", "QS": "q", "Soll": 10, "Ist": None, "Datum": None, "Z1": "A", "Z2": "B"})
    result = forecast(pd.DataFrame(rows), MAP)
    assert list(result.rows.values())[-1].length == 10.0  # das 4. gezogene Kabel (40) zählt nicht mehr


def test_forecast_ignores_short_ends():
    result = forecast(frame(), MAP, ignore_short=True, min_length=6)
    assert result.total.total == 5  # Kabel f (Soll 5) fällt weg


def test_parse_date_variants():
    assert parse_date("30.12.26") == date(2026, 12, 30)
    assert parse_date("1.2.2027") == date(2027, 2, 1)
    assert parse_date("2026-10-21T00:00") == date(2026, 10, 21)
    assert parse_date("kein datum") is None and parse_date(None) is None


def test_daily_report():
    text = daily_report_text(frame(), MAP, "Test", generated=datetime(2026, 10, 22, 8, 0))
    assert "== 21.10.26 ==" in text and "Gesamt: 2 Kabel, 22 m" in text
    assert "  3x1,5: 2 Kabel, 22 m" in text and "== 22.10.26 ==" in text
    assert text.index("== 21.10.26") < text.index("== 22.10.26") < text.index("== Summe ==")
    ranged = daily_report_text(frame(), MAP, start=date(2026, 10, 22), generated=datetime(2026, 10, 22))
    assert "== 21.10.26" not in ranged and "5x2,5: 1 Kabel, 6 m" in ranged
