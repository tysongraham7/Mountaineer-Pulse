"""
Mountaineer Pulse - Player Name Reconciliation
==============================================
Two feeds name the same player differently. The CFBD portal gives legal names
("Ezekiel Durham-Campbell", "Cameron Griffin"); the scraped wvusports roster
gives what the school prints ("Zeke Durham-Campbell", "Cam Griffin"). Nobody is
wrong, but an exact-string join treats them as two people -- which showed the
same player twice on the projected roster AND blocked his previous-school stats,
because those attach by roster id.

The roster is the authority: it's what fans see on the jersey. So this module
maps a feed name onto the roster spelling.

Matching is deliberately conservative -- a wrong merge fuses two real players,
which is worse than leaving a duplicate. A candidate must be the ONLY plausible
match on that roster, and must clear one of:

  1. exact match after normalizing (accents, punctuation, suffixes, case)
  2. same last name + one first name prefixes the other   (Cam / Cameron)
  3. same last name + a known nickname pair               (Zeke / Ezekiel)
  4. same first name + last names differ by one edit      (Rawlison / Rawlinson)

Anything else is reported, not guessed.
"""

import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Only nicknames a prefix check can't catch. Cam/Cameron, Matt/Matthew and friends
# already pass rule 2, so they don't belong here.
NICKNAMES = [
    {"ezekiel", "zeke"},
    {"robert", "bob", "rob", "bobby"},
    {"william", "bill", "will", "billy"},
    {"james", "jim", "jimmy"},
    {"andrew", "drew", "andy"},
    {"john", "jack", "johnny"},
    {"richard", "dick", "rick", "richie"},
    {"charles", "chuck", "charlie"},
    {"henry", "hank"},
    {"edward", "ed", "ted", "teddy"},
    {"anthony", "tony"},
    {"joseph", "joe", "joey"},
    {"michael", "mike", "mikey"},
    {"lawrence", "larry"},
    {"kenneth", "kenny"},
    {"gerald", "jerry"},
    {"donald", "don", "donnie"},
    {"ronald", "ron", "ronnie"},
    {"patrick", "pat"},
    {"francis", "frank"},
]


def norm_name(name: str) -> str:
    """Fold a name to a comparable key: no accents, punctuation, suffixes, or case.

    Runs of single letters collapse, so "D.J. Epps" and "DJ Epps" agree.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace(".", " ").replace("'", "").replace("-", " ")
    tokens = [t for t in s.split() if t and t not in SUFFIXES]
    # Leading initials become one token: ["d", "j", "epps"] -> ["dj", "epps"].
    lead = 0
    while lead < len(tokens) and len(tokens[lead]) == 1:
        lead += 1
    if lead > 1:
        tokens = ["".join(tokens[:lead])] + tokens[lead:]
    return " ".join(tokens)


def split_name(name: str) -> tuple[str, str]:
    """(first, last) from a normalized name. Multi-word surnames stay together."""
    parts = norm_name(name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein. Used only to allow a single typo in a surname."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 1:
        return 2  # more than one edit apart; exact value doesn't matter
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _nickname_of(a: str, b: str) -> bool:
    return any(a in group and b in group for group in NICKNAMES)


def same_person(a: str, b: str) -> bool:
    """True when two names plausibly denote one player. Conservative by design."""
    if not a or not b:
        return False
    if norm_name(a) == norm_name(b):
        return True
    fa, la = split_name(a)
    fb, lb = split_name(b)
    if not la or not lb:
        return False
    if la == lb:
        # Cam / Cameron, or Zeke / Ezekiel.
        if fa and fb and (fa.startswith(fb) or fb.startswith(fa)):
            return True
        if _nickname_of(fa, fb):
            return True
    if fa == fb and _edit_distance(la, lb) == 1:
        return True
    return False


def canonical(name: str, roster_names: list[str]) -> str | None:
    """Return the roster's spelling of `name`, or None if it isn't unambiguous.

    Ambiguity is a refusal, not a coin flip: two brothers on one roster (same
    surname, one first name a prefix of the other) must never be merged.
    """
    hits = [r for r in roster_names if same_person(name, r)]
    if len(hits) != 1:
        return None
    return hits[0]


def reconcile(names: list[str], roster_names: list[str]) -> tuple[dict, list, list]:
    """Map feed names onto roster spellings.

    Returns (renames, unmatched, ambiguous):
      renames   {feed_name: roster_name} where the two differ and the match is sure
      unmatched feed names with no roster counterpart (genuinely new, or a typo)
      ambiguous feed names matching more than one roster player -- never merged
    """
    renames, unmatched, ambiguous = {}, [], []
    for n in names:
        hits = [r for r in roster_names if same_person(n, r)]
        if len(hits) > 1:
            ambiguous.append((n, hits))
        elif not hits:
            unmatched.append(n)
        elif norm_name(hits[0]) != norm_name(n):
            renames[n] = hits[0]
    return renames, unmatched, ambiguous
