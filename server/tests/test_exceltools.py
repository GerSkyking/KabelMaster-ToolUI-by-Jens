import json
from io import BytesIO

from openpyxl import Workbook, load_workbook


def _book(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _post(client, path, source, target, cfg, apply=False):
    return client.post(f"/api/exceltools/{path}", data={"config": json.dumps(cfg), "apply": str(apply).lower()},
                       files={"source": ("quelle.xlsx", source), "target": ("ziel.xlsx", target)})


def test_requires_login(client):
    assert client.post("/api/exceltools/inspect", files={"file": ("a.xlsx", b"x")}).status_code == 401


def test_inspect_lists_sheets_and_columns(admin):
    data = _book({"A": [["Kabel", "Länge"], ["W1", 1]], "B": [["X"]]})
    r = admin.post("/api/exceltools/inspect", files={"file": ("a.xlsx", data)})
    assert r.status_code == 200
    sheets = r.json()["sheets"]
    assert [s["name"] for s in sheets] == ["A", "B"]
    assert sheets[0]["columns"] == [{"name": "Kabel", "letter": "A"}, {"name": "Länge", "letter": "B"}]


def test_inspect_rejects_garbage(admin):
    assert admin.post("/api/exceltools/inspect", files={"file": ("a.xlsx", b"kein excel")}).status_code == 422


def test_transfer_preview_and_apply(admin):
    source = _book({"S": [["Kabel", "Länge", "Von"], ["W1", 10, "A"], [" w2 ", 20, None], ["W9", 5, "Z"], ["W1", 99, "dup"]]})
    target = _book({"T": [["Nr", "Länge", "Info"], ["W1", 1, "x"], ["W2.0", 2, "y"], ["W2", None, "z"], ["W3", 3, "q"]]})
    cfg = {"source_key": "Kabel", "target_key": "Nr", "pairs": [{"source": "Länge", "target": "Länge"}, {"source": "Von", "target": "Von neu"}]}
    preview = _post(admin, "transfer", source, target, cfg).json()
    assert preview["rows_matched"] == 2  # W1 und W2 (" w2 " in der Quelle: Leerraum/Groß-Klein egal)
    assert preview["new_columns"] == ["Von neu"]
    assert preview["missing_in_source"] == ["W2.0", "W3"]
    assert preview["only_in_source"] == ["W9"]
    assert preview["duplicate_keys"] == ["W1"]
    assert preview["cells_changed"] > 0

    r = _post(admin, "transfer", source, target, cfg, apply=True)
    assert r.status_code == 200
    ws = load_workbook(BytesIO(r.content))["T"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("Nr", "Länge", "Info", "Von neu")
    assert rows[1] == ("W1", 10, "x", "A")  # erster Treffer der Quelle gilt
    assert rows[3] == ("W2", 20, "z", None)
    assert rows[4] == ("W3", 3, "q", None)  # nicht in der Quelle: unverändert


def test_transfer_keeps_existing_and_ignores_empty(admin):
    source = _book({"S": [["Kabel", "Länge"], ["W1", 10], ["W2", None]]})
    target = _book({"T": [["Kabel", "Länge"], ["W1", 5], ["W2", 7]]})
    cfg = {"source_key": "Kabel", "target_key": "Kabel", "pairs": [{"source": "Länge"}], "overwrite": "empty"}
    assert _post(admin, "transfer", source, target, cfg).json()["cells_kept"] == 1
    cfg = {"source_key": "Kabel", "target_key": "Kabel", "pairs": [{"source": "Länge"}]}
    out = _post(admin, "transfer", source, target, cfg, apply=True)
    rows = list(load_workbook(BytesIO(out.content)).active.iter_rows(values_only=True))
    assert rows[1:] == [("W1", 10), ("W2", 7)]  # leerer Quellwert überschreibt nichts


def test_transfer_unknown_column(admin):
    data = _book({"S": [["Kabel"], ["W1"]]})
    r = _post(admin, "transfer", data, data, {"source_key": "Nope", "target_key": "Kabel", "pairs": [{"source": "Kabel"}]})
    assert r.status_code == 422 and "Nope" in r.json()["detail"]


def test_fill_searches_all_sheets_and_all_cells(admin):
    source = _book({"S": [["Schlüssel", "Wert"], ["W1", "rot"], ["W2", "blau"], ["W7", "grün"]]})
    target = _book({
        "Eins": [["Pos", "Kabel", "Farbe"], [1, "W1", None], [2, "w3", None]],
        "Zwei": [["Text", "Farbe", "Rest"], ["Kabel W2 hier", None, None], ["W2", "alt", None]],
        "Drei": [["Nix", "Anders"], ["W1", 1]],
    })
    cfg = {"source_key": "Schlüssel", "source_value": "Wert", "target_column": "Farbe"}
    preview = _post(admin, "fill", source, target, cfg).json()
    assert preview["keys_total"] == 3 and preview["keys_found"] == 2
    assert preview["not_found"] == ["W7"]
    assert preview["sheets_skipped"] == ["Drei"]  # keine Spalte "Farbe"

    out = _post(admin, "fill", source, target, cfg, apply=True)
    wb = load_workbook(BytesIO(out.content))
    assert [c.value for c in wb["Eins"]["C"]] == ["Farbe", "rot", None]
    assert [c.value for c in wb["Zwei"]["B"]] == ["Farbe", None, "blau"]  # ganze Zelle muss der Schlüssel sein


def test_fill_by_column_letter_and_key_column(admin):
    source = _book({"S": [["K", "V"], ["A1", 5]]})
    target = _book({"T": [["x", "y", "z"], ["A1", "A1", None], [None, None, None]]})
    cfg = {"source_key": "K", "source_value": "V", "target_column": "C", "target_key_column": "y"}
    out = _post(admin, "fill", source, target, cfg, apply=True)
    assert list(load_workbook(BytesIO(out.content)).active.iter_rows(values_only=True))[1] == ("A1", "A1", 5)
