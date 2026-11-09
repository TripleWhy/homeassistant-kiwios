"""Constants for the Ampere.IQ integration."""

import aiohttp

DOMAIN = "ampere_iq_smartbox_homeassistant"

# Cookie the device uses to keep an authenticated session.
CONF_KIWISESSIONID = "kiwisessionid"

# Timeouts for the single session used to talk to the device.
SESSION_TIMEOUT = aiohttp.ClientTimeout(
    total=60, connect=30, sock_connect=10, sock_read=30
)
