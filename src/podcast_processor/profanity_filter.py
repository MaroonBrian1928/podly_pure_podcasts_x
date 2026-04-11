import math
import re
from typing import Any

PROFANITY_PAD_MS = 40
PROFANITY_MERGE_GAP_MS = 80

# Keep the default list intentionally conservative to avoid surprising false
# positives when applying destructive audio edits.
# Keep the default list intentionally conservative to avoid surprising false
# positives when applying destructive audio edits.
DEFAULT_PROFANITY_TERMS = frozenset(
    {
        "arse",
        "arses",
        "ass",
        "asses",
        "asshat",
        "asshats",
        "asshole",
        "assholes",
        "bastard",
        "bastards",
        "bitch",
        "bitches",
        "bitching",
        "bloody",
        "bollocks",
        "boner",
        "boners",
        "boob",
        "boobs",
        "booby",
        "booty",
        "bs",
        "bullcrap",
        "bullshit",
        "bullshits",
        "bullshitting",
        "butthole",
        "buttholes",
        "cock",
        "cocks",
        "crap",
        "crappy",
        "crotch",
        "crotches",
        "cunt",
        "cunts",
        "dammit",
        "damn",
        "damned",
        "damnit",
        "dick",
        "dicks",
        "dildo",
        "dildos",
        "dipshit",
        "dipshits",
        "douche",
        "douchebag",
        "douchebags",
        "douches",
        "fag",
        "fags",
        "fart",
        "farts",
        "farted",
        "farting",
        "frick",
        "fricking",
        "frigging",
        "fuck",
        "fucked",
        "fucker",
        "fuckers",
        "fucking",
        "fuckin",
        "fucks",
        "goddamn",
        "goddammit",
        "goddamnit",
        "hell",
        "horny",
        "jerkoff",
        "jerkoffs",
        "motherfucker",
        "motherfuckers",
        "motherfucking",
        "nipple",
        "nipples",
        "penis",
        "penises",
        "pissed",
        "piss",
        "pisser",
        "pisses",
        "pissing",
        "poop",
        "pooped",
        "pooping",
        "poops",
        "porn",
        "porno",
        "prick",
        "pricks",
        "pussy",
        "pussies",
        "scrotum",
        "scrotums",
        "sex",
        "sexy",
        "shit",
        "shits",
        "shitted",
        "shitty",
        "shitting",
        "slut",
        "sluts",
        "sonofabitch",
        "suck",
        "sucked",
        "sucker",
        "sucks",
        "tit",
        "tits",
        "titties",
        "titty",
        "twat",
        "twats",
        "vagina",
        "vaginas",
        "wank",
        "wanked",
        "wanker",
        "wankers",
        "wanking",
        "whore",
        "whores",
    }
)


def extract_profanity_windows(
    segments: list[Any],
    *,
    profanity_terms: frozenset[str] = DEFAULT_PROFANITY_TERMS,
    pad_ms: int = PROFANITY_PAD_MS,
    merge_gap_ms: int = PROFANITY_MERGE_GAP_MS,
) -> tuple[list[tuple[int, int]], bool]:
    raw_windows: list[tuple[int, int]] = []
    saw_word_timestamps = False

    for segment in segments or []:
        words = getattr(segment, "words", None) or []
        if words:
            saw_word_timestamps = True

        for word in words:
            raw_word = getattr(word, "word", None)
            start = getattr(word, "start", None)
            end = getattr(word, "end", None)
            if raw_word is None or start is None or end is None:
                continue

            normalized = _normalize_word(str(raw_word))
            if not normalized or normalized not in profanity_terms:
                continue

            start_ms = max(0, math.floor(float(start) * 1000.0) - pad_ms)
            end_ms = max(start_ms + 1, math.ceil(float(end) * 1000.0) + pad_ms)
            raw_windows.append((start_ms, end_ms))

    return _merge_windows(raw_windows, gap_ms=merge_gap_ms), saw_word_timestamps


def _normalize_word(word: str) -> str:
    return re.sub(r"(^[^A-Za-z0-9']+)|([^A-Za-z0-9']+$)", "", word).lower()


def _merge_windows(
    windows: list[tuple[int, int]],
    *,
    gap_ms: int,
) -> list[tuple[int, int]]:
    if not windows:
        return []

    merged: list[tuple[int, int]] = []
    for start_ms, end_ms in sorted(windows):
        if not merged:
            merged.append((start_ms, end_ms))
            continue

        prev_start_ms, prev_end_ms = merged[-1]
        if start_ms <= prev_end_ms + gap_ms:
            merged[-1] = (prev_start_ms, max(prev_end_ms, end_ms))
            continue

        merged.append((start_ms, end_ms))

    return merged
