"""Deterministic acceptance for the generic CSV analysis capability."""
import csv
import io
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest

from backend.app.agent_execution.tools import (
    analyze_general,
    choose_analysis_mode,
    parse_dataset_csv,
    validate_output,
)


def task(csv_text):
    return {
        "csvText": csv_text,
        "inputHash": "a" * 64,
        "desired_input_revision": 3,
    }


def test_generic_profile_computes_numeric_and_missing_values():
    profile = parse_dataset_csv(
        "student,score,attempts\nAri,10,1\nBea,20,\nCy,30,3\n"
    )

    assert profile["rowCount"] == 3
    assert profile["headers"] == ["student", "score", "attempts"]
    assert profile["columns"] == [
        {"column": "student", "type": "text", "count": 3, "missing": 0, "uniqueValues": 3,
         "minimum": None, "maximum": None, "mean": None, "median": None},
        {"column": "score", "type": "number", "count": 3, "missing": 0, "uniqueValues": 3,
         "minimum": 10.0, "maximum": 30.0, "mean": 20.0, "median": 20.0},
        {"column": "attempts", "type": "number", "count": 2, "missing": 1, "uniqueValues": 2,
         "minimum": 1.0, "maximum": 3.0, "mean": 2.0, "median": 2.0},
    ]


@pytest.mark.parametrize(
    "value, message",
    [
        ("name,Name\na,b\n", "unique"),
        ("name,score\nAri,10\nBea\n", "different number of columns"),
        ("name,score\n", "at least one data row"),
    ],
)
def test_generic_csv_rejects_ambiguous_or_malformed_data(value, message):
    with pytest.raises(ValueError, match=message):
        parse_dataset_csv(value)


def test_generic_csv_treats_nan_tokens_as_missing_values():
    profile = parse_dataset_csv("score\n10\nNaN\n")
    assert profile["columns"][0]["missing"] == 1
    assert profile["columns"][0]["mean"] == 10


def test_csv_mode_keeps_specialized_lab_contract_and_accepts_general_profile():
    mode, constraints = choose_analysis_mode(
        "trial,distance,time\n1,10,2\n", "Use centimeters"
    )
    assert mode == "lab"
    assert constraints["distanceUnit"] == "cm"

    mode, constraints = choose_analysis_mode(
        "week,attendance\n1,25\n2,30\n", "Summarize this dataset"
    )
    assert mode == "general"
    assert constraints == {}


def test_general_analysis_outputs_are_independently_readable_and_revision_linked():
    result = analyze_general(task("week,attendance,note\n1,25,quiz\n2,35,project\n3,,final\n"))

    assert "Profiled 3 rows across 3 columns" in result["summary"]
    assert "not causal analysis" in result["summary"]
    assert result["completion"]["status"] == "verified"
    assert {item["name"] for item in result["outputs"]} == {
        "analysis.xlsx", "analysis.csv", "analysis.pdf", "report.json"
    }
    assert all(item["lineage"]["inputRevision"] == 3 for item in result["outputs"])
    for output in result["outputs"]:
        validate_output(output)

    output_csv = next(item for item in result["outputs"] if item["name"] == "analysis.csv")
    rows = list(csv.DictReader(io.StringIO(output_csv["content"].decode("utf-8"))))
    attendance = next(row for row in rows if row["column"] == "attendance")
    assert attendance["mean"] == "30.0"
    assert attendance["median"] == "30.0"
    assert attendance["missing"] == "1"

    report = json.loads(next(item for item in result["outputs"] if item["name"] == "report.json")["content"])
    assert report["inputRevision"] == 3
    assert report["rowCount"] == 3
    assert len(report["limitations"]) >= 2

    workbook = next(item for item in result["outputs"] if item["name"] == "analysis.xlsx")
    with zipfile.ZipFile(io.BytesIO(workbook["content"])) as archive:
        assert archive.testzip() is None
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    assert len(sheet.findall("x:sheetData/x:row", ns)) == 4

    pdf = next(item for item in result["outputs"] if item["name"] == "analysis.pdf")
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf["content"])
    try:
        assert len(document) == 1
        assert document[0].render(scale=0.5).width > 0
    finally:
        document.close()


def test_general_csv_output_escapes_spreadsheet_formula_headers():
    result = analyze_general(task("=1+1,value\nnot-a-formula,4\n"))
    output_csv = next(item for item in result["outputs"] if item["name"] == "analysis.csv")
    rows = list(csv.DictReader(io.StringIO(output_csv["content"].decode("utf-8"))))
    assert rows[0]["column"] == "'=1+1"


def test_output_verifier_rejects_truncated_pdf_and_corrupt_workbook():
    result = analyze_general(task("score\n1\n2\n"))
    pdf = next(item for item in result["outputs"] if item["name"] == "analysis.pdf")
    with pytest.raises(Exception):
        validate_output({**pdf, "content": b"%PDF-1.4\ntruncated"})

    workbook = next(item for item in result["outputs"] if item["name"] == "analysis.xlsx")
    with pytest.raises(Exception):
        validate_output({**workbook, "content": b"not a zip"})
