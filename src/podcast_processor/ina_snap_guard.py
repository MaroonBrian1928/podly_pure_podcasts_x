"""Deterministic INA snap guard for refined ad boundaries.

The word-boundary refiner works from text alone and sometimes ends an ad
block a few seconds into the resumed content (a false positive: real
episode audio is cut). INA's acoustic segmentation usually marks the true
ad end with a silence gap -- on one golden-set episode the refiner
overshot by 7.6s and the INA "noEnergy" segment sat exactly on the true
end. This guard encodes the policy that a backtest over 54 refined
boundaries from 16 ear-reviewed episodes validated ("Variant E+"):

END boundaries only. A refined end is snapped earlier when ALL hold:

* Trigger: the end falls strictly inside an INA "speech" segment
  (>0.3s from its edges). A boundary already sitting at an acoustic
  edge is probably right and is left alone.
* Target: the end of the LONGEST "noEnergy" (silence) segment whose end
  lies inside the block within the tolerance window before the end.
* No veto: no "music" segment starts within 2s after the end (the
  boundary is already anchored by a sting), and no other refined block
  starts within 15s after the end (shared break / cluster).
* The move is at least MIN_MOVE_SECONDS (sub-second adjustments are
  noise under the cutter's crossfade).

Start boundaries are never snapped: the same backtest showed
start-snapping produced no fixes and two false-negative harms (it can
resurrect an ad sign-off that sits at a block's start). The guard never
expands a cut (shrink-only), so it can only recover content the refiner
over-cut, never eat more of it.

Deferral to the sting anchor: when the sting tier already adjusted a
block's END earlier in the same pass, the boundary dict carries a
"sting_anchor" audit entry with an "original_end" key, and this guard
leaves that end alone -- the sting's measured onset is the stronger
signal, and snapping again can only shrink the cut into an in-ad
silence, undoing the anchor's fix (the 2397 composition failure). The
deferral is edge-precise: a block whose START was sting-anchored but
whose end was not still receives end-snapping (the 2409 composition,
where the two tiers fix opposite edges of one break). Without the
sting tier the audit key never appears, so this is a no-op there.

Every adjustment is returned to the caller, which records it on the
stored boundary under the "ina_snap" key and logs it, so a later
"why did this cut land here?" can be attributed exactly:
classifier block (orig_end) -> refiner (ina_snap.original_end) ->
snap guard (refined_end).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("global_logger")

TOLERANCE_SECONDS = 8.0
MIN_MOVE_SECONDS = 1.0
TRIGGER_EDGE_EPSILON_SECONDS = 0.3
MUSIC_VETO_SECONDS = 2.0
CLUSTER_VETO_SECONDS = 15.0

SPEECH_LABEL = "speech"
SILENCE_LABEL = "noEnergy"
MUSIC_LABEL = "music"


@dataclass(frozen=True)
class AcousticSegment:
    """One INA segmentation row (start/end in seconds, INA label)."""

    start: float
    end: float
    label: str


@dataclass(frozen=True)
class SnapAdjustment:
    """A single applied snap, for logging and the stored audit key."""

    block_index: int
    original_end: float
    snapped_end: float
    silence_start: float
    silence_end: float


def _sting_end_anchor(boundary: dict[str, Any]) -> dict[str, Any] | None:
    """The boundary's sting END-anchor audit entry, if one was applied.

    The sting tier stores its audit under "sting_anchor": a single dict
    when one edge moved, or a list of two dicts when both did. An entry
    is an END anchor iff it carries "original_end" (START anchors carry
    "original_start" instead).
    """
    anchor = boundary.get("sting_anchor")
    if isinstance(anchor, dict):
        entries = [anchor]
    elif isinstance(anchor, list):
        entries = [entry for entry in anchor if isinstance(entry, dict)]
    else:
        return None
    for entry in entries:
        if "original_end" in entry:
            return entry
    return None


def apply_ina_snap_guard(
    boundaries: list[dict[str, Any]],
    segments: list[AcousticSegment],
) -> tuple[list[dict[str, Any]], list[SnapAdjustment]]:
    """Apply the snap guard to a post's refined boundaries.

    ``boundaries`` are the dicts about to be stored on the post (each has
    ``refined_start`` / ``refined_end``); ``segments`` is the post's INA
    segmentation, sorted by start time. Returns a new boundary list
    (inputs are not mutated) and the adjustments that were applied.
    Adjusted boundaries gain an ``ina_snap`` audit key holding the
    pre-snap end and the silence segment that justified the move.
    A boundary whose END the sting tier already anchored (a
    ``sting_anchor`` entry with ``original_end``) is deferred to and
    left untouched; a sting START anchor alone does not defer the end.
    """
    if not boundaries or not segments:
        return [dict(b) for b in boundaries], []

    starts = [float(b["refined_start"]) for b in boundaries]
    result: list[dict[str, Any]] = []
    adjustments: list[SnapAdjustment] = []

    for index, boundary in enumerate(boundaries):
        new_boundary = dict(boundary)
        result.append(new_boundary)
        start = float(boundary["refined_start"])
        end = float(boundary["refined_end"])

        # Deferral: the sting tier already anchored this block's end in
        # the same pass; its measured onset outranks INA silence, and
        # snapping here would shrink the cut past the anchor's fix.
        sting_end = _sting_end_anchor(boundary)
        if sting_end is not None:
            logger.info(
                "INA snap guard: block %d end %.2f deferred to sting anchor "
                "(sting original end %.2f, score %.2f, onset %.2f)",
                index,
                end,
                float(sting_end.get("original_end", end)),
                float(sting_end.get("score", 0.0)),
                float(sting_end.get("onset", 0.0)),
            )
            continue

        # Trigger: the end must fall strictly inside a speech segment.
        if not any(
            seg.label == SPEECH_LABEL
            and seg.start + TRIGGER_EDGE_EPSILON_SECONDS
            < end
            < seg.end - TRIGGER_EDGE_EPSILON_SECONDS
            for seg in segments
        ):
            continue

        # Target: the longest silence whose end is inside the block and
        # within the tolerance window before the end.
        candidates = [
            seg
            for seg in segments
            if seg.label == SILENCE_LABEL
            and start + MIN_MOVE_SECONDS <= seg.end <= end - MIN_MOVE_SECONDS
            and end - seg.end <= TOLERANCE_SECONDS
        ]
        if not candidates:
            continue
        silence = max(candidates, key=lambda seg: (seg.end - seg.start, seg.end))
        snapped_end = silence.end
        if end - snapped_end < MIN_MOVE_SECONDS:
            continue

        # Veto 1: a music sting starting right after the end means the
        # boundary is already anchored; leave it alone.
        if any(
            seg.label == MUSIC_LABEL and 0.0 <= seg.start - end <= MUSIC_VETO_SECONDS
            for seg in segments
        ):
            continue

        # Veto 2: another block starting right after this end means a
        # shared break; snapping one block's end inside a cluster is
        # unsafe (it can only widen the kept gap between the blocks).
        if any(0.0 < other - end <= CLUSTER_VETO_SECONDS for other in starts):
            continue

        new_boundary["refined_end"] = snapped_end
        new_boundary["ina_snap"] = {
            "original_end": end,
            "silence_start": silence.start,
            "silence_end": silence.end,
        }
        adjustments.append(
            SnapAdjustment(
                block_index=index,
                original_end=end,
                snapped_end=snapped_end,
                silence_start=silence.start,
                silence_end=silence.end,
            )
        )

    return result, adjustments
