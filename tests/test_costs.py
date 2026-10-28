from types import SimpleNamespace

from costs import Tally, price_for


def response(model, inp, out, cache_write=0, cache_read=0):
    usage = SimpleNamespace(input_tokens=inp, output_tokens=out,
                            cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read)
    return SimpleNamespace(model=model, usage=usage)


def test_price_lookup_prefers_longest_match():
    assert price_for("claude-sonnet-5-5") == (2.00, 10.00)
    assert price_for("claude-opus-5-5") == (4.00, 20.00)
    assert price_for("claude-opus-5") == (5.00, 25.00)
    assert price_for("claude-unknown-9") is None


def test_dollars_include_cache_pricing():
    t = Tally()
    # 1M fresh in ($2) + 1M out ($10) + 1M cache write ($2.50) + 1M cache read ($0.20)
    t.record(response("claude-sonnet-5-5", 1_000_000, 1_000_000, 1_000_000, 1_000_000))
    assert round(t.dollars, 6) == 14.70
    assert t.input_tokens == 3_000_000 and t.output_tokens == 1_000_000 and t.calls == 1


def test_add_and_describe():
    a, b = Tally(), Tally()
    a.record(response("claude-haiku-5-5", 10_000, 2_000))
    b.record(response("claude-mystery", 100, 100))
    a.add(b)
    assert a.calls == 2
    assert a.describe() == "2 calls, 10,100 in / 2,100 out tokens, $0.0020 (plus unpriced: claude-mystery)"
