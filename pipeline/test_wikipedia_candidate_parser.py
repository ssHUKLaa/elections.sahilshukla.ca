"""Regression checks for adjacent candidate and party-stripe parsing."""

from build_wikipedia_ballots import parse_candidates


def main() -> None:
    assert parse_candidates(
        "▌Stacy Garrity (Republican)[62] "
        "▌Ken Krawchuk (Libertarian) [63] "
        "▌Josh Shapiro (Democratic)[62]"
    ) == [
        ("Stacy Garrity", "Republican", False),
        ("Ken Krawchuk", "Libertarian", False),
        ("Josh Shapiro", "Democratic", False),
    ]
    assert parse_candidates("▌▌Nick LaLota (Republican)") == [
        ("Nick LaLota", "Republican", False),
    ]
    assert parse_candidates("▌John (Max) Smith (Independent, write-in)[4]") == [
        ("John (Max) Smith", "Independent", True),
    ]
    print("Wikipedia candidate parser checks passed")


if __name__ == "__main__":
    main()
