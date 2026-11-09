"""Constants for the KiwiOS integration."""

import aiohttp

DOMAIN = "kiwios"

# Prefix of the aggregated REST API of firmware running KiwiOS Edge.
EDGE_API_PATH = "/rest/hems-configurator"

# Cookie the device uses to keep an authenticated session.
CONF_KIWISESSIONID = "kiwisessionid"

# Timeouts for the single session used to talk to the device.
SESSION_TIMEOUT = aiohttp.ClientTimeout(
    total=60, connect=30, sock_connect=10, sock_read=30
)
