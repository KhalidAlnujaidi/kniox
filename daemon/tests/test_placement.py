import placement

def test_parses_simple_header():
    assert placement.parse_placement("# kniox: placement=cluster\nimport os\n") == {
        "placement": "cluster", "hints": {}}

def test_parses_hints():
    out = placement.parse_placement("#!/usr/bin/env python\n# kniox: placement=cluster mem=2G task=scrape\n")
    assert out == {"placement": "cluster", "hints": {"mem": "2G", "task": "scrape"}}

def test_missing_header_returns_none():
    assert placement.parse_placement("import os\nprint(1)\n") is None

def test_invalid_placement_returns_none():
    assert placement.parse_placement("# kniox: placement=mars\n") is None

def test_only_scans_first_20_lines():
    body = "\n" * 25 + "# kniox: placement=cluster\n"
    assert placement.parse_placement(body) is None
