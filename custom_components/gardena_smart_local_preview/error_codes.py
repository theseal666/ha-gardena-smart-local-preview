# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Names for the error codes a mower reports.

The local API carries no table to resolve a code to text: the model
definitions describe `last_error_code` as a plain number, the gateway's
resource descriptions give only its range, and nothing on the gateway maps it
either. The names here are therefore built one at a time, and a code is only
added once its meaning has been observed on a device rather than guessed.

Confirming a code takes two readings of the same event: the number this
integration reports, and the text the device itself gives it at the same
timestamp — the mower's display, or the notification the GARDENA app pushes.
Lists of error codes for other manufacturers' mowers are not evidence for
this one.

Every name needs a matching `state` entry under `sensor.last_error` in each
translation file.
"""

from __future__ import annotations

# Confirmed on a smart SILENO city/life (with LONA), model 53988:
# four start attempts without a valid loop signal reported code 2, and the
# GARDENA app pushed "No loop signal" at those same four timestamps.
GEN1_MOWER_ERRORS: dict[int, str] = {
    0: "none",
    2: "no_loop_signal",
    # Reported at 02:40 on a night the air was at 0.6 °C, by a mower that had
    # just driven out; the GARDENA app called it "temporary battery problem"
    # nine minutes later, and no other error was reported in between. Weaker
    # evidence than code 2 above, which matched four events to the minute.
    62: "temporary_battery_problem",
}

# Reported for a code that has no confirmed name yet. The raw number stays in
# the entity's `code` attribute, so an unnamed error is still actionable.
UNKNOWN_ERROR = "unknown"


def error_name(code: int) -> str:
    """Return the name of an error code, or `unknown` for an unnamed one."""
    return GEN1_MOWER_ERRORS.get(code, UNKNOWN_ERROR)


def error_names() -> list[str]:
    """Return every state the error sensor can report."""
    return sorted(set(GEN1_MOWER_ERRORS.values()) | {UNKNOWN_ERROR})
