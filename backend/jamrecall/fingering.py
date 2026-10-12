"""Inferred guitar fingering for a monophonic note sequence.

The detected MIDI pitch is the observation; the string/fret chosen here is an *estimate*. Most
pitches can be played in several places, so we also report how many alternatives existed.
Invariant: for every assigned position, OPEN_STRINGS[string] + fret == midi_pitch.
"""

from __future__ import annotations

from dataclasses import dataclass

METHOD = "dp-hand-window-v1"
# String number (1 = high E) -> open-string MIDI pitch, standard tuning E2 A2 D3 G3 B3 E4.
OPEN_STRINGS = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}
MAX_FRET = 20


@dataclass(frozen=True)
class Position:
    string: int
    fret: int


@dataclass(frozen=True)
class Fingering:
    position: Position | None  # None: pitch not playable in standard tuning up to MAX_FRET
    alternatives: int  # number of other playable positions for this pitch


def positions_for(midi: int) -> list[Position]:
    return [
        Position(s, midi - open_)
        for s, open_ in sorted(OPEN_STRINGS.items(), reverse=True)
        if 0 <= midi - open_ <= MAX_FRET
    ]


def _node_cost(p: Position) -> float:
    # Mild preference for lower positions; extra penalty above the 12th fret.
    return 0.05 * p.fret + (0.5 if p.fret > 12 else 0.0)


HAND_SPAN = 4  # frets covered by the fretting hand without shifting


def _windows(p: Position, current: int | None) -> list[int | None]:
    """Hand-window start frets from which p can be played (open strings keep the hand put)."""
    if p.fret == 0:
        return [current]
    return list(range(max(1, p.fret - HAND_SPAN + 1), p.fret + 1))


def _shift_cost(before: int | None, after: int | None) -> float:
    if before is None or after is None:
        return 0.0
    return float(abs(after - before))


def assign(midis: list[int]) -> list[Fingering]:
    """Viterbi over candidate positions; unplayable notes break the chain and get None."""
    result: list[Fingering] = []
    segment: list[int] = []

    def flush() -> None:
        if segment:
            result.extend(_assign_segment(segment))
            segment.clear()

    for m in midis:
        if positions_for(m):
            segment.append(m)
        else:
            flush()
            result.append(Fingering(None, 0))
    flush()
    return result


def _assign_segment(midis: list[int]) -> list[Fingering]:
    # DP state: (candidate index, hand-window start fret or None before the hand is placed).
    State = tuple[int, int | None]
    cands = [positions_for(m) for m in midis]
    layer: dict[State, tuple[float, State | None]] = {}
    for k, p in enumerate(cands[0]):
        for w in _windows(p, None):
            _keep_min(layer, (k, w), _node_cost(p), None)
    layers = [layer]
    for i in range(1, len(cands)):
        nxt: dict[State, tuple[float, State | None]] = {}
        for state, (c, _) in layers[-1].items():
            for k, p in enumerate(cands[i]):
                for w in _windows(p, state[1]):
                    total = c + _shift_cost(state[1], w) + _node_cost(p)
                    _keep_min(nxt, (k, w), total, state)
        layers.append(nxt)
    state: State | None = min(layers[-1], key=lambda s: layers[-1][s][0])
    chosen: list[int] = []
    for i in range(len(cands) - 1, -1, -1):
        assert state is not None
        chosen.append(state[0])
        state = layers[i][state][1]
    chosen.reverse()
    return [Fingering(cands[i][chosen[i]], len(cands[i]) - 1) for i in range(len(cands))]


def _keep_min(layer: dict, key: tuple, cost: float, back: tuple | None) -> None:
    if key not in layer or cost < layer[key][0]:
        layer[key] = (cost, back)
