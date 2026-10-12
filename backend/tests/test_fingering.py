import random

from jamrecall.fingering import HAND_SPAN, MAX_FRET, OPEN_STRINGS, assign, positions_for


def test_every_playable_pitch_maps_back_to_same_pitch():
    for midi in range(30, 100):
        for p in positions_for(midi):
            assert OPEN_STRINGS[p.string] + p.fret == midi
            assert 0 <= p.fret <= MAX_FRET


def test_range_limits():
    assert positions_for(39) == []  # below low E
    assert positions_for(40)[0].string == 6 and positions_for(40)[0].fret == 0
    assert positions_for(64 + MAX_FRET)  # highest fret on high E
    assert positions_for(64 + MAX_FRET + 1) == []


def test_assignment_preserves_pitch_for_random_sequences():
    rng = random.Random(7)
    for _ in range(200):
        seq = [rng.randint(35, 90) for _ in range(rng.randint(1, 30))]
        result = assign(seq)
        assert len(result) == len(seq)
        for midi, f in zip(seq, result, strict=True):
            if f.position is None:
                assert positions_for(midi) == []
            else:
                assert OPEN_STRINGS[f.position.string] + f.position.fret == midi
                assert f.alternatives == len(positions_for(midi)) - 1


def test_scale_stays_in_one_region():
    # A minor pentatonic should be playable inside one 4-fret hand window (the 5th-position box).
    seq = [57, 60, 62, 64, 67, 69, 72]
    frets = [f.position.fret for f in assign(seq) if f.position.fret > 0]
    assert max(frets) - min(frets) <= HAND_SPAN - 1


def test_unplayable_note_breaks_chain_without_crash():
    out = assign([45, 20, 47])
    assert out[1].position is None and out[1].alternatives == 0
    assert out[0].position is not None and out[2].position is not None
