import contextvars
import math

scientific_notation: contextvars.ContextVar[bool] = contextvars.ContextVar("scientific_notation", default=False)

SCIENTIFIC_THRESHOLD = 1_000_000


def _scientific(value: float) -> str:
    exponent = int(math.floor(math.log10(abs(value))))
    mantissa = value / 10 ** exponent
    if round(abs(mantissa), 2) >= 10:
        mantissa /= 10
        exponent += 1
    return f"{mantissa:.2f}".rstrip("0").rstrip(".") + f"e{exponent}"


def use_scientific(value: float) -> bool:
    return scientific_notation.get() and abs(value) >= SCIENTIFIC_THRESHOLD


def format_number(value: float) -> str:
    if use_scientific(value):
        return _scientific(value)
    return f"{value:,}"


def format_integer(value: int) -> str:
    if use_scientific(value):
        return _scientific(value)
    return f"{int(value):,}".replace(",", ".")
