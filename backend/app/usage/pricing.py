"""Integer arithmetic; token totals include billable reasoning exactly once."""
from decimal import Decimal, ROUND_CEILING


def price(component: str, quantities: dict, cost_nano: int = 0) -> int:
    def q(name):
        value = quantities.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError('Invalid metering quantity.')
        return value
    if isinstance(cost_nano, bool) or not isinstance(cost_nano, int) or cost_nano < 0:
        raise ValueError('Invalid provider liability.')
    if component == 'model':
        cached = q('cached_tokens')
        prompt = q('input_tokens')
        if cached > prompt: raise ValueError('Cached tokens exceed input.')
        reference = (prompt-cached)*500 + cached*100 + q('output_tokens')*2000
    elif component == 'stt': reference = (q('milliseconds')*10_000_000+59_999)//60_000
    elif component == 'tts': reference = q('characters')*60_000
    elif component == 'voice': reference = (q('milliseconds')*15_000_000+59_999)//60_000
    elif component == 'browser': reference = (q('milliseconds')*5_000_000+59_999)//60_000
    elif component in {'tool', 'sandbox', 'search', 'proxy'}: reference = 0
    else: raise ValueError('Unsupported usage component.')
    # One USD nanodollar equals one microcredit at the chosen exchange rate.
    return max(reference, (cost_nano*5+3)//4)


def dollars_to_nano(value):
    return int((Decimal(str(value))*10**9).to_integral_value(rounding=ROUND_CEILING))
