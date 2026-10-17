# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

DOMAIN = "gardena_smart_local_preview"

DEFAULT_PORT = 8443
DEFAULT_VALVE_DURATION_MINUTES = 30
DEFAULT_POWER_DURATION_MINUTES = 30
DEFAULT_PUMP_DURATION_MINUTES = 30
DEFAULT_MOWER_DURATION_HOURS = 6

# The longest position reporting session a mower accepts in one request
POSITION_REPORTING_SECONDS = 3600
# Re-requested this often while the switch is on, so reporting covers a whole
# mowing session instead of stopping after the first hour
POSITION_REPORTING_REARM_SECONDS = 3000

# Subentry data key holding {str(valve_id): minutes} for a device's valves
CONF_VALVE_DURATIONS = "valve_durations"
# Subentry data key holding a power outlet's default timed-on duration, in minutes
CONF_POWER_DURATION = "power_duration"
# Subentry data key holding a pump's default timed-start duration, in minutes
CONF_PUMP_DURATION = "pump_duration"
# Subentry data key holding a mower's default manual-start duration, in hours
CONF_MOWER_DURATION = "mower_duration"
