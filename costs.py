"""Token and dollar tally for the Claude calls in a run.

Prices are USD per million tokens (Anthropic list prices, October 2026).
Cache writes cost 1.25x the input price and cache reads 0.1x. Update PRICES
if a model or its price changes; an unknown model is counted in tokens but
reported as unpriced rather than guessed.
"""
PRICES = {  # model: (input, output)
    "claude-haiku-5-5":  (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5":   (2.00, 10.00),
    "claude-opus-5-5":   (4.00, 20.00),
    "claude-opus-5":     (5.00, 25.00),
    "claude-opus-4-8":   (5.00, 25.00),
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


def price_for(model):
    """Longest matching id wins, so "claude-sonnet-5-5" never prices as "claude-sonnet-5"."""
    matches = [m for m in PRICES if model == m or model.startswith(m + "-")]
    return PRICES[max(matches, key=len)] if matches else None


class Tally:
    def __init__(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.dollars = 0.0
        self.unpriced_models = set()

    def add(self, other):
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.dollars += other.dollars
        self.unpriced_models |= other.unpriced_models

    def record(self, response):
        """Adds one API response. `response.model` is the model that actually
        served it, which differs from the requested one after a fallback."""
        u = response.usage
        fresh = u.input_tokens or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        out = u.output_tokens or 0

        self.calls += 1
        self.input_tokens += fresh + cache_write + cache_read
        self.output_tokens += out
        price = price_for(response.model)
        if price is None:
            self.unpriced_models.add(response.model)
            return
        inp, outp = price
        self.dollars += (fresh * inp
                         + cache_write * inp * CACHE_WRITE_MULTIPLIER
                         + cache_read * inp * CACHE_READ_MULTIPLIER
                         + out * outp) / 1_000_000

    def describe(self):
        text = (f"{self.calls} call{'s' if self.calls != 1 else ''}, "
                f"{self.input_tokens:,} in / {self.output_tokens:,} out tokens, ${self.dollars:.4f}")
        if self.unpriced_models:
            text += f" (plus unpriced: {', '.join(sorted(self.unpriced_models))})"
        return text
