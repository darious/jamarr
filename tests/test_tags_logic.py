from datetime import date


from app.scanner.tags import _normalize_release_type, _parse_date_strict

# --- Release Type Tests ---

def test_normalize_release_type():
    # Album cases
    assert _normalize_release_type("album") == "album"
    assert _normalize_release_type("Album") == "album"
    # assert _normalize_release_type("album;live") == "album" # OLD rule: album wins
    # New rule: live wins. So this is no longer "album" in the "Album cases" block, strictly speaking.
    # But let's leave simple album cases here.
    assert _normalize_release_type("experimental;album") == "album"
    assert _normalize_release_type("compilation") == "compilation"
    assert _normalize_release_type("album; compilation") == "compilation"

    # Live cases
    assert _normalize_release_type("live") == "live"
    assert _normalize_release_type("live; bootleg") == "live"
    # But album;live -> live (new rule)
    assert _normalize_release_type("album;live") == "live"
    assert _normalize_release_type("live;album") == "live"

    # Compilation cases
    assert _normalize_release_type("compilation") == "compilation"
    assert _normalize_release_type("soundtrack") == "compilation"
    assert _normalize_release_type("remix") == "compilation"
    assert _normalize_release_type("dj-mix") == "compilation"
    assert _normalize_release_type("mixtape/street") == "compilation"
    assert _normalize_release_type("demo") == "album"

    # EP
    assert _normalize_release_type("ep") == "ep"
    assert _normalize_release_type("EP") == "ep"

    # Single
    assert _normalize_release_type("single") == "single"
    
    # Other / Fallback
    assert _normalize_release_type("bootleg") == "album"
    assert _normalize_release_type("unknown") == "album"
    
    # Empty / None
    assert _normalize_release_type(None) == "album"
    assert _normalize_release_type("") == "album"

# --- Date Parsing Tests ---

class MockFile:
    def __init__(self, tags):
        self.tags = tags

def test_parse_date_strict_precision():
    # Precision: Full > Year
    f = MockFile({
        "DATE": "2000-01-01",
        "ORIGINALYEAR": "1999"
    })
    d, raw, tag = _parse_date_strict(f, {})
    assert d == date(2000, 1, 1)
    assert tag == "DATE"

    # Precision: Month > Year
    f = MockFile({
        "DATE": "2000-05",
        "ORIGINALYEAR": "1999"
    })
    d, raw, tag = _parse_date_strict(f, {})
    assert d == date(2000, 5, 1)
    assert tag == "DATE"
    
    # Precision: Year vs Year (Priority List Tiebreaker)
    # ORIGINALYEAR is lower index (higher priority) than YEAR
    f = MockFile({
        "YEAR": "2000",
        "ORIGINALYEAR": "1999"
    })
    d, raw, tag = _parse_date_strict(f, {})
    assert d == date(1999, 1, 1)
    assert tag == "ORIGINALYEAR"

def test_parse_date_strict_priority():
    # Full Date Priority: MUSICBRAINZ_ORIGINAL_RELEASE_DATE > DATE
    f = MockFile({
        "DATE": "2000-01-01",
        "MUSICBRAINZ_ORIGINAL_RELEASE_DATE": "1999-12-31"
    })
    d, raw, tag = _parse_date_strict(f, {})
    assert d == date(1999, 12, 31)
    assert tag == "MUSICBRAINZ_ORIGINAL_RELEASE_DATE"

def test_parse_date_strict_formats():
    # YYYY-MM-DD
    f = MockFile({"DATE": "2023-12-25"})
    d, _, _ = _parse_date_strict(f, {})
    assert d == date(2023, 12, 25)

    # YYYY/MM/DD
    f = MockFile({"DATE": "2023/12/25"})
    d, _, _ = _parse_date_strict(f, {})
    assert d == date(2023, 12, 25)

    # YYYY.MM.DD
    f = MockFile({"DATE": "2023.12.25"})
    d, _, _ = _parse_date_strict(f, {})
    assert d == date(2023, 12, 25)

    # YYYY-MM
    f = MockFile({"DATE": "2023-07"})
    d, _, _ = _parse_date_strict(f, {})
    assert d == date(2023, 7, 1)

    # YYYY
    f = MockFile({"DATE": "2023"})
    d, _, _ = _parse_date_strict(f, {})
    assert d == date(2023, 1, 1)

def test_parse_date_strict_invalid():
    f = MockFile({"DATE": "not-a-date"})
    d, _, _ = _parse_date_strict(f, {})
    assert d is None

def test_parse_date_multiple_values_list():
    # If a tag has a list of values, should check all
    # e.g. DATE=['2000', '2001-01-01'] -> 2001-01-01 wins on precision
    f = MockFile({"DATE": ["2000", "2001-01-01"]})
    d, raw, tag = _parse_date_strict(f, {})
    assert d == date(2001, 1, 1)
    assert tag == "DATE"

if __name__ == "__main__":
    try:
        test_normalize_release_type()
        print("test_normalize_release_type passed")
        test_parse_date_strict_precision()
        print("test_parse_date_strict_precision passed")
        test_parse_date_strict_priority()
        print("test_parse_date_strict_priority passed")
        test_parse_date_strict_formats()
        print("test_parse_date_strict_formats passed")
        test_parse_date_strict_invalid()
        print("test_parse_date_strict_invalid passed")
        test_parse_date_multiple_values_list()
        print("test_parse_date_multiple_values_list passed")
        print("test_parse_date_multiple_values_list passed")
        print("ALL TESTS PASSED")
    except AssertionError as e:
        print(f"TEST FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        exit(1)

