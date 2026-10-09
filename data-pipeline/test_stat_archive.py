"""
Mountaineer Pulse - Checks for the stat archive
===============================================
sync_stat_archive.py's decoding, identity rules and leaderboard math, against small
hand-built rows shaped like wvusports.com's. The cases are the real faults found while
backfilling: Smallwood's yards on Crawford's page, Kansas's lineup filed under WVU,
initials splitting a career. No network, no database.

Run:  python test_stat_archive.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_stat_archive as m


def row(linked, filed, jersey="1", **stats):
    return {"isAFooterStat": False, "playerName": linked, "nameFromStats": filed,
            "playerUniform": jersey, "playerImageUrl": "/images/x.jpg", **stats}


def football(rushing=(), defense=(), scoring=(), games="12"):
    total = {"isAFooterStat": True, "playerName": "Total", "gamesPlayed": games}
    return {"overallIndividualStats": {"individualStats": {
        "individualRushingStats": [total, *rushing],
        "individualDefensiveStats": list(defense),
        "individualScoringStats": list(scoring)}}, "record": "8-5, 5-4"}


def archive_of(*seasons):
    """[(season, Season)] -> stat_archive-shaped rows."""
    out = []
    for yr, s in seasons:
        out += m.archive_rows("football", yr, s)
    return out


def test_nuxt_payload_decodes_references():
    # devalue: values are indexes into the array; -1 is undefined; Reactive wraps.
    arr = [{"pinia": 1}, ["Reactive", 2], {"name": 3, "nums": 4, "gone": -1}, "WVU", [5, 5], 7]
    html = f'<script type="application/json" id="__NUXT_DATA__">{json.dumps(arr)}</script>'
    assert m.nuxt_state(html) == {"pinia": {"name": "WVU", "nums": [7, 7], "gone": None}}


def test_names_and_numbers():
    assert m.display_name("Fox Jr., Scotty") == "Scotty Fox Jr."
    assert m.display_name("SHELL,RUSHEL") == "Rushel Shell"
    assert m.display_name("II,TONY FIELDS") == "Tony Fields II", "suffix filed as the surname"
    assert m.innings_to_outs("534.1") == 1603, "innings are thirds, not tenths"
    assert m.num("59.412%") == 59.412 and m.num(".361") == 0.361 and m.num("NaN") is None
    assert m.fmt_value(0.361, "avg") == ".361" and m.fmt_value(1.088, "avg") == "1.088"


def test_mislinked_line_goes_to_the_stat_file_name():
    s = m.parse_season("football", football(rushing=[
        row("Crawford, Antonio", "SMALLWOOD,W", "4", gamesPlayed="13", attempts="238", net="1519"),
        row("Shell, Rushel", "SHELL,RUSHEL", "7", gamesPlayed="12", attempts="161", net="708"),
    ]))
    assert "antonio crawford" not in s.players, "Crawford never ran for 1,519 yards"
    w = s.players["w smallwood"]
    assert w["stats"]["rushing.yds"] == 1519 and w["photo"] is None, "Crawford's photo dropped"
    assert s.players["rushel shell"]["photo"], "a correct link keeps its photo"


def test_opponent_box_score_is_dropped_but_a_kicker_is_not():
    s = m.parse_season("football", football(
        rushing=[row("Howard, Skyler", "PIERSON,TONY", "3", gamesPlayed="1", attempts="1", net="-4"),
                 row("Howard, Skyler", "HOWARD,SKYLER", "3", gamesPlayed="13", attempts="157", net="502")],
        scoring=[row("Davisson, Nick", "MOLINA,MIKE", "86", points="3"),
                 row("Molina, Mike", "MOLINA,MIKE", "86", points="90")]))
    assert "tony pierson" not in s.players and "PIERSON,TONY (linked to Howard, Skyler)" in s.dropped
    assert s.players["skyler howard"]["stats"]["rushing.yds"] == 502, "Kansas's -4 isn't his"
    # No games column in the scoring table, but MOLINA,MIKE is linked right on another row,
    # so the mislinked row is his too -- and a second row of one table is more games.
    assert s.players["mike molina"]["stats"]["scoring.pts"] == 93


def test_nameless_kicking_row_borrows_its_specialist_name():
    block = football(defense=[row("Jackson, Josiah", "HAYES,MICHAEL", "22", gamesPlayed="13", totalTackles="1")],
                     scoring=[row("Jackson, Josiah", "HAYES,MICHAEL", "22", points="97")])
    block["overallIndividualStats"]["individualStats"]["individualFieldGoalStats"] = [
        row("Jackson, Josiah", "", "22", made="17", attempts="21")]
    s = m.parse_season("football", block)
    assert s.players["michael hayes"]["stats"]["kicking.fgm"] == 17, "2023: Hayes's field goals"
    assert "josiah jackson" not in s.players


def test_roster_completes_initials_and_merges_spellings():
    s = m.parse_season("football", football(defense=[
        row("Smallwood, W", "SMALLWOOD,W", "4", gamesPlayed="13", totalTackles="1"),
        row("Riddick, Shaq", "RIDDICK,SHAQ", "", gamesPlayed="3", totalTackles="4"),
        row("Riddick, Shaquille", "RIDDICK,SHAQUILLE", "4", gamesPlayed="12", totalTackles="30"),
    ]))
    roster = [{"name": "Wendell Smallwood", "jersey": "4", "position": "RB", "photo": "s.jpg"},
              {"name": "Shaquille Riddick", "jersey": "4", "position": "DE", "photo": "r.jpg"}]
    assert m.apply_roster(s, roster) == 2
    assert s.players["wendell smallwood"]["position"] == "RB", "matched by name, not shared #4"
    sr = s.players["shaquille riddick"]
    assert sr["stats"]["defense.tkl"] == 34, "two rows in one table are different games"
    assert sr["stats"]["general.gp"] == 12, "games played is the same count seen twice"


def test_visitors_need_all_three_marks():
    s = m.parse_season("mbb", {"overallIndividualStats": {"individualStats": [
        {"isAFooterStat": True, "playerName": "Total", "gamesPlayed": "34"},
        row("Trimble, Melo", "", "2", gamesPlayed="1", points="20"),
        row("Carter, Jevon", "", "2", gamesPlayed="34", points="300"),
        row("Hadley, Late", "", "9", gamesPlayed="1", points="2"),
    ]}, "record": "25-10"})
    roster = [{"name": "Jevon Carter", "jersey": "2", "position": "G", "photo": None}]
    m.apply_roster(s, roster)
    known = {"Late Hadley": {2016}}   # played for WVU another season
    assert m.drop_visitors(s, 2015, roster, known) == ["Melo Trimble"]
    assert m.drop_visitors(s, 2015, [], {}) == [], "no roster page, no judgement"


def test_reconcile_initials_without_merging_two_people():
    def season(rows):
        return m.parse_season("football", football(defense=rows))
    arch = archive_of(
        (2014, season([row("Benton, Al-Rasheed", "BENTON,AL-RASHEED", "17", gamesPlayed="13", totalTackles="60")])),
        (2016, season([row("Benton, A", "BENTON,A", "", gamesPlayed="13", totalTackles="70"),
                       row("Robinson, J", "ROBINSON,J", "", gamesPlayed="12", totalTackles="5"),
                       row("Robinson, Justin", "ROBINSON,JUSTIN", "2", gamesPlayed="12", totalTackles="9")])),
        (2022, season([row("Robinson, Jimmori", "ROBINSON,JIMMORI", "0", gamesPlayed="12", totalTackles="40")])),
    )
    canon = m.reconcile_keys(arch)
    assert canon["a benton"] == canon["al rasheed benton"], "hyphenated first name, two years on"
    assert canon["j robinson"] != canon["justin robinson"], "initial beside a full name in one table"
    assert canon["j robinson"] != canon["jimmori robinson"], "six years apart is not one career"


def test_leaderboards_rank_ties_qualify_and_floor_best_seasons():
    def bsb(yr, games, pitchers):
        s = m.parse_season("baseball", {"overallIndividualStats": {"individualStats": {
            "individualPitchingStats": [row(n, "", "1", appearances="5", inningsPitched=ip,
                                            earnedRunsAllowed=er, meetsMinPitchingStats=True)
                                        for n, ip, er in pitchers]}},
            "overallTeamStats": {"teamStats": {"ourWinsLosses": f"{games}-0"}}, "record": ""})
        return m.archive_rows("baseball", yr, s)
    arch = (bsb(2019, 60, [("Manoah, Alek", "108.1", "25"), ("Kessler, Sam", "60.0", "20")])
            + bsb(2020, 16, [("Wolf, Jackson", "25.2", "3")]))
    rows = m.build_leaders("baseball", arch, {2019: 60, 2020: 16})
    era = lambda scope, season=0: [(r["player_name"], r["display"]) for r in rows
                                   if r["board"] == "era" and r["scope"] == scope and r["season"] == season]
    assert era("season", 2020) == [("Jackson Wolf", "1.05")], "he led his own short season"
    assert era("best")[0] == ("Alek Manoah", "2.08"), "but 25 innings isn't a best-ever season"
    wins = [r for r in rows if r["board"] == "ip" and r["scope"] == "career"]
    assert wins[0]["player_name"] == "Alek Manoah" and wins[0]["display"] == "108.1"

    tie = m.rank_board({"asc": False, "fmt": "int"}, [(5, "a"), (7, "b"), (5, "c"), (3, "d")])
    assert [r[0] for r in tie] == [1, 2, 2, 4], "standard competition ranking"


def test_record_book_merge():
    def bsb(yr, hitters):
        s = m.parse_season("baseball", {"overallIndividualStats": {"individualStats": {
            "individualHittingStats": [row(n, "", "1", gamesPlayed="50", atBats=ab, hits=h, homeRuns=hr)
                                       for n, ab, h, hr in hitters]}},
            "overallTeamStats": {"teamStats": {"ourWinsLosses": "40-20"}}, "record": ""})
        return m.archive_rows("baseball", yr, s)
    # McBroom 2011-14 in the book; suppose he'd played on into 2015 (archive).
    arch = (bsb(2015, [("McBroom, Ryan", "200", "60", "10"), ("New, Slugger", "220", "90", "20")])
            + bsb(2016, [("New, Slugger", "210", "80", "15")]))
    book = {"source": "test", "through": 2014, "lists": [
        {"key": "hr", "title": "Home Runs", "group": "Power", "fmt": "int", "scope": "career", "entries": [
            {"name": "Tim McCabe", "value": 35, "seasons": [2000, 2003]},
            {"name": "Ryan McBroom", "value": 30, "seasons": [2011, 2014]}]},
        {"key": "hr", "title": "Home Runs", "group": "Power", "fmt": "int", "scope": "season", "entries": [
            {"name": "Mark Landers", "value": 19, "season": 1994}]},
        {"key": "avg", "title": "Batting Average", "group": "Hitting", "fmt": "avg", "scope": "career", "entries": [
            {"name": "Ryan McBroom", "value": 0.380, "seasons": [2011, 2014]},
            {"name": "Old Timer", "value": 0.350, "seasons": [1960, 1962]}]},
    ]}
    rows = m.merge_record_book("baseball", book, arch)
    pick = lambda scope, key: [(r["rank"], r["player_name"], r["display"], r["detail"]) for r in rows
                               if r["scope"] == scope and r["list_key"] == key]
    assert pick("career", "hr") == [(1, "Ryan McBroom", "40", "2011-15"), (2, "Tim McCabe", "35", "2000-03"),
                                    (2, "Slugger New", "35", "2015-16")], \
        "book through 2014 + archive 2015 add; a tie at the last place stays on"
    assert pick("season", "hr") == [(1, "Slugger New", "20", "2015")]
    assert pick("career", "avg") == [(1, "Slugger New", ".395", "2015-16"), (2, "Ryan McBroom", ".380", "2011-14")], \
        "a new career joins a rate list, but a listed one isn't recombined with his .300 in 2015"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
