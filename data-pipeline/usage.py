"""
Mountaineer Pulse - Claude API usage accounting
===============================================
Records what each pipeline call actually consumed, so "what does this cost per day"
is a query instead of a guess.

Tokens are read straight off the API response and are exact. Prices are not: they're
a local table that has to be kept in step with Anthropic's published pricing. A model
missing from the table logs its tokens with a null cost rather than inventing a
number -- a wrong dollar figure is worse than an absent one, because it looks
authoritative.

Never raises. Accounting must not be able to take down the briefing.
"""

from datetime import date

# USD per million tokens: (input, output). Cache reads bill at a tenth of input and
# cache writes at 1.25x, which is the standard Anthropic ratio.
# Check these against https://www.anthropic.com/pricing when a model is added.
PRICES = {
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}

# Sonnet 5 launched at a reduced rate. Encoded with its end date rather than left as a
# comment, so the briefing's cost doesn't silently understate by a third the morning the
# introductory period ends -- which is the day it would matter most to notice.
INTRO_PRICING = {
    "claude-sonnet-5": ((2.00, 10.00), date(2026, 8, 31)),
}

# Server-side web search, billed per request on top of the tokens it pulls in.
WEB_SEARCH_USD = 10.00 / 1000


def _price(model: str):
    """Exact key first, then longest known prefix, so dated model ids still match."""
    intro = INTRO_PRICING.get(model)
    if intro and date.today() <= intro[1]:
        return intro[0]
    if model in PRICES:
        return PRICES[model]
    hits = [k for k in PRICES if model.startswith(k)]
    return PRICES[max(hits, key=len)] if hits else None


def summarize(model: str, resp) -> dict:
    """Pull the usage numbers off a Messages response."""
    return summarize_usage(model, getattr(resp, "usage", None))


def summarize_usage(model: str, u, searches: int | None = None) -> dict:
    """Cost a usage object directly.

    Separate from summarize() because generate_briefing resumes pause_turn loops and
    counts its own search blocks, so it holds a usage object and a search count rather
    than a single response.
    """
    get = lambda name: int(getattr(u, name, 0) or 0) if u else 0  # noqa: E731
    if searches is None:
        searches = 0
        server = getattr(u, "server_tool_use", None) if u else None
        if server is not None:
            searches = int(getattr(server, "web_search_requests", 0) or 0)

    row = {
        "model": model,
        "input_tokens": get("input_tokens"),
        "output_tokens": get("output_tokens"),
        "cache_read": get("cache_read_input_tokens"),
        "cache_write": get("cache_creation_input_tokens"),
        "web_searches": searches,
        "cost_usd": None,
    }

    p = _price(model)
    if p:
        pin, pout = p
        row["cost_usd"] = round(
            (row["input_tokens"] * pin
             + row["output_tokens"] * pout
             + row["cache_read"] * pin * 0.10
             + row["cache_write"] * pin * 1.25) / 1_000_000
            + row["web_searches"] * WEB_SEARCH_USD,
            5,
        )
    return row


def log(sb, script: str, model: str, resp) -> None:
    """Record one call. Prints a one-line summary and stores the row."""
    _emit(sb, script, model, lambda: summarize(model, resp))


def log_raw(sb, script: str, model: str, u, searches: int | None = None) -> None:
    """Record a call when you hold the usage object rather than the response."""
    _emit(sb, script, model, lambda: summarize_usage(model, u, searches))


def _emit(sb, script: str, model: str, build) -> None:
    try:
        row = build()
    except Exception as e:                                    # noqa: BLE001
        print(f"    (usage: could not read response usage -- {e.__class__.__name__})")
        return

    cost = f"${row['cost_usd']:.4f}" if row["cost_usd"] is not None else "cost n/a"
    extra = f" · {row['web_searches']} searches" if row["web_searches"] else ""
    print(f"    usage: {row['input_tokens']:,} in / {row['output_tokens']:,} out"
          f"{extra} · {cost}  [{model}]")
    if row["cost_usd"] is None:
        print(f"    (no price on file for {model} — add it to usage.PRICES)")

    try:
        sb.table("api_usage").insert({"script": script, **row}).execute()
    except Exception as e:                                    # noqa: BLE001
        print(f"    (usage: not stored -- {e.__class__.__name__})")


def client_and_logger(script: str):
    """Convenience for scripts that build their own Supabase client elsewhere."""
    return lambda sb, model, resp: log(sb, script, model, resp)
