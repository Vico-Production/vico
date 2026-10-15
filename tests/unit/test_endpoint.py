from app.audio.endpoint import SILENCE_S, SILENCE_SHORT_S, Endpointer


def feed(ep, levels, start=0.0, step=0.05):
    t = start
    for level in levels:
        if ep.feed(level, t):
            return t
        t += step
    return None


def test_waits_for_a_real_pause_after_speech():
    ep = Endpointer()
    quiet = [0.01] * 20  # 1 s of room noise: nothing heard yet, never "finished"
    assert feed(ep, quiet) is None and not ep.heard
    speech = [0.4] * 60  # 3 s of talking
    ended = feed(ep, quiet + speech + [0.01] * 60)
    assert ended is not None
    # finished only after the full pause, not at the first quiet moment
    assert ended - (1.0 + 3.0) >= SILENCE_S - 0.06


def test_a_short_start_gets_a_longer_pause():
    ep = Endpointer()
    ended = feed(ep, [0.4] * 10 + [0.01] * 80)  # half a second ("Vico, can you...") then a pause
    assert ended is not None and ended - 0.5 >= SILENCE_SHORT_S - 0.06


def test_pauses_inside_a_sentence_do_not_end_it():
    ep = Endpointer()
    talk = ([0.4] * 30 + [0.01] * 16) * 3 + [0.4] * 20  # pauses of 0.8 s between phrases
    assert feed(ep, talk) is None and ep.heard
