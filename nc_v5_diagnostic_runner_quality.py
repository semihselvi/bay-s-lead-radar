from __future__ import annotations

import re

import main_v5_5 as radar

# Human-reviewed false positive: "Ищу дом ... на 1 день" is an explicit
# short-term rental request, not a buy/rent ambiguity worth qualifying.
_EXTRA_SHORT_STAY = (
    r"(?:"
    r"\bна\s+\d+\s+(?:день|дня|дней|сутки|суток|ночь|ночи|ночей)\b|"
    r"\bна\s+сутки\b|\bна\s+один\s+день\b"
    r")"
)
radar.TG_SHORT_STAY_RE = re.compile(
    rf"(?:{radar.TG_SHORT_STAY_RE.pattern}|{_EXTRA_SHORT_STAY})",
    re.I | re.S,
)

# Import the existing diagnostic wrapper only after the quality patch so its
# reject-reason instrumentation sees the same production rules.
import nc_v5_diagnostic_runner as diagnostics  # noqa: E402,F401


if __name__ == "__main__":
    radar.main()
