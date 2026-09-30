"""
Mountaineer Pulse - Checks for the Ourlads depth chart
======================================================
ourlads.py's parser and sync_depth.py's override rules, against a trimmed copy of the
real page's markup. No network, no database.

Run:  python test_ourlads.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ourlads
from sync_depth import football_entries

EMPTY = "<td></td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td>"


def row(pos, *players):
    cells = "".join(f"<td>1</td><td><a href='x' class='lc_gold'>{p}</a></td>" for p in players)
    return f"<tr class='row-dc-wht'><td class='row-dc-wht'>{pos}</td>{cells}{EMPTY}</tr>"


def page(offense, defense, special="", reserves=""):
    tb = lambda i, rows: f'<tbody id="ctl00_phContent_dcTBody{i}">{rows}</tbody>'
    return ("<html><div>Updated: 09/26/2026 5:00PM ET</div>"
            + tb("", offense) + tb("2", defense) + tb("3", special) + tb("4", reserves) + "</html>")


PAGE = page(
    row("WR-X", "Bray, Jaden RS SR/TR", "Francis, Taron RS FR/TR")
    + row("WR-Y", "Epps, DJ RS SR/TR", "Weaver-Bomar, Armoni RS FR")
    + row("QB", "Hawkins Jr., Michael RS SO/TR", "Fox Jr., Scotty SO"),
    row("DE", "Durham-Campbell, Zeke RS SR/TR", "Wiley, Darius RS SO/TR")
    + row("NB", "Latimer II, Geimere SR/TR", "Khatri, Miles FR")
    + row("SS", "Williams, Da&#39;Mare RS SO/TR"),
    row("PR", "Epps, DJ RS SR/TR", "Sieg, Matt FR"),
    row("RES", "Strachan, Prince RS JR/TR", "Doe, John JR"),
)


def chart():
    return ourlads.parse(PAGE)


def names(entries, pos):
    return [e["player_name"] for e in sorted(entries, key=lambda e: e["rank"]) if e["position"] == pos]


def test_parse():
    c = chart()
    assert c["updated"] == "09/26/2026 5:00PM ET"
    got = {(r["position"], r["rank"]): (r["player_name"], r["class_year"]) for r in c["rows"]}
    assert got[("QB", 1)] == ("Michael Hawkins Jr.", "R-So."), "suffix stays on the surname"
    assert got[("QB", 2)] == ("Scotty Fox Jr.", "So.")
    assert got[("NB", 1)] == ("Geimere Latimer II", "Sr."), "/TR is dropped"
    assert got[("SS", 1)] == ("Da'Mare Williams", "R-So."), "HTML entities decoded"
    assert got[("WR-Y", 1)] == ("DJ Epps", "R-Sr."), "an all-caps first name isn't a class"
    assert ("WR-X", 3) not in got, "empty depth slots are skipped"
    assert {r["unit"] for r in c["rows"] if r["position"] == "RES"} == {"Reserves"}


def test_no_overrides_is_just_ourlads():
    fb, _ = football_entries(chart(), [])
    assert names(fb, "WR-X") == ["Jaden Bray", "Taron Francis"]
    assert all(e["status"] == "active" for e in fb)
    assert not any(e["position"] == "RES" for e in fb), "reserves aren't a position"
    order = list(dict.fromkeys(e["position"] for e in fb))
    assert order.index("QB") < order.index("WR-X"), "QB-first, not Ourlads' receivers-first"


def test_hurt_starter_on_reserves_goes_back_struck():
    ov = [{"sport_id": "football", "position": "WR-X", "rank": 1, "player_name": "Prince Strachan",
           "status": "out", "note": "Injured"}]
    fb, report = football_entries(chart(), ov)
    assert names(fb, "WR-X") == ["Prince Strachan", "Jaden Bray", "Taron Francis"]
    strachan = next(e for e in fb if e["player_name"] == "Prince Strachan")
    assert strachan["status"] == "out" and strachan["class_year"] == "R-Jr."
    assert any("John Doe" in l for l in report), "an unexplained reserve is reported"
    assert not any("Strachan" in l for l in report)


def test_injury_on_the_chart_spreads_status_but_not_the_pulse_hit():
    ov = [{"sport_id": "football", "position": "WR-Y", "player_name": "DJ Epps",
           "status": "out", "pulse_delta": -2, "out_since": "2026-09-20", "note": "Ankle"}]
    fb, report = football_entries(chart(), ov)
    epps = [e for e in fb if e["player_name"] == "DJ Epps"]
    assert {e["position"]: e["status"] for e in epps} == {"WR-Y": "out", "PR": "out"}
    assert sum(e.get("pulse_delta") or 0 for e in epps) == -2, "counted once, not per spot"
    assert names(fb, "WR-Y")[0] == "DJ Epps", "Ourlads' order is kept"
    assert any("still on Ourlads" in l for l in report)


def test_pin_and_stale():
    ov = [{"sport_id": "football", "position": "FB", "rank": 1, "player_name": "Kayden Luke",
           "class_year": "Jr.", "status": "active", "pin": True},
          {"sport_id": "football", "position": "QB", "rank": 1, "player_name": "Garrett Greene",
           "status": "active"}]
    fb, report = football_entries(chart(), ov)
    assert names(fb, "FB") == ["Kayden Luke"]
    assert next(e for e in fb if e["position"] == "FB")["unit"] == "Offense"
    assert "Garrett Greene" not in [e["player_name"] for e in fb]
    assert any("Garrett Greene" in l and "stale" in l for l in report)


def test_incomplete_page_is_refused():
    assert ourlads.looks_complete(ourlads.parse("<html></html>"))
    assert ourlads.looks_complete(chart()), "the fixture is too short to pass as a full chart"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
