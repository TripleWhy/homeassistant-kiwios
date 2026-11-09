# KiwiOS for Home Assistant

Custom integration for Home Assistant that reads measurements from devices running
**KiwiOS**, the energy management software used by the **EKD Ampere.IQ Smartbox**
(sold by Energiekonzepte Deutschland). Because KiwiOS also reports on the
products connected to it, the integration is named after the software rather
than the box it happens to run on.

## Naming

| Name | Domain | What it is |
| --- | --- | --- |
| KiwiOS | `kiwios` | The integration. This is what you set up. |
| EKD Ampere.IQ Smartbox (local REST API) | `ampere_iq_smartbox_local` | A [virtual integration](https://developers.home-assistant.io/docs/creating_integration_manifest#virtual-integration): a manifest-only alias that points at `kiwios`, so the product can be listed under its sales name. |

There is more than one way to reach EKD hardware, and they differ in what they
offer:

- **Local REST API** — what this integration speaks: the box answers on the
  local network. Local, no cloud, polling. Which measurements are available
  depends on the firmware, see [Firmware generations](#firmware-generations).
- **Modbus** — the box reaches the devices it manages over Modbus TCP, and some
  of them (inverter, battery) can be polled directly. This is the only local
  way to the per-device details that recent firmware stopped publishing over
  HTTP, and the box exposes the connection settings of each device in
  `/rest/hems-configurator/things` (`config.host`, `config.port`,
  `config.unitId`). Polling Modbus is not part of this integration.
- **Traffic capture** — on your own network the box can be observed while it
  talks: Modbus to the devices it manages, TLS to the EKD cloud. The device
  side carries exactly the values the box itself sees, so a capture shows what
  is available without asking the box for anything.
- **EKD cloud service** — what the "Ampere.IQ" Android app talks to. It offers
  official API keys, and the app's traffic can be reverse engineered.

The alias is therefore named after the transport this integration implements,
so it does not claim to be *the* EKD integration.

Virtual integrations are a core-only feature. Home Assistant only forwards the
`supported_by` target for built-in integrations, so in a custom (HACS) install
the alias shows up in the integration metadata but cannot start the KiwiOS setup
flow. Set up **KiwiOS** directly; the alias becomes fully functional once this
integration is accepted into Home Assistant Core. `hassfest` applies the core
integration schema to custom integrations and therefore reports the alias as
invalid, which is expected until then.

## Installation

### HACS

1. Add `https://github.com/TripleWhy/ampere_iq_smartbox_homeassistant` as a custom
   repository of type *Integration*.
2. Install **KiwiOS** and restart Home Assistant.
3. Go to *Settings → Devices & services → Add integration* and pick **KiwiOS**.

### Manual

Copy `custom_components/kiwios` into your `config/custom_components/` directory
and restart Home Assistant.

## Configuration

The setup form asks for the URL of the device (for example
`http://192.0.2.10`) and, only when the device asks for one, the installer
password. The session cookie is stored in the config entry, so polling keeps
working without logging in again.

The integration asks the device which API it serves and adapts to it.

### Firmware generations

**Older firmware** serves the OpenHAB style per-channel API. Every channel of
`/rest/things` becomes a sensor, fetched from `/rest/items`. Each measurement
that carries a device-side timestamp also gets a matching `… Timestamp` sensor,
which is disabled by default; enable it in the entity settings if you need to
know when a value was measured. This is the complete view: state of charge,
energy counters, temperatures, per-string PV data and so on.

**KiwiOS Edge** (KiwiOS Edge 10.x, EM.setup 4.x) removed that API — `/rest/things`
and `/rest/items` answer with `404`. What is left is a small aggregated API under
`/rest/hems-configurator`, which is what this integration uses in that case:

| Endpoint | Sensors |
| --- | --- |
| `energy-overview` | Production, Feed-in, Feed-out, Household consumption, Storage power in, Storage power out |
| `power-indicator` | one power sensor per device (purchase, production, consumption) |
| `things` | one status sensor per device |
| `pv-plants` | peak power, curtailment and installation date per PV plant |
| `public/gateway/info` | the KiwiOS Edge version, and the gateway device itself |

These are instantaneous values only. Recent firmware publishes no state of
charge, no energy counters and no temperatures over HTTP at all — they are gone
from the box, not hidden behind a setting. Modbus or a traffic capture are the
remaining local options for those; see above.

## Upgrading from `ampere_iq_smartbox_homeassistant`

The integration used to be published under the domain
`ampere_iq_smartbox_homeassistant`. Home Assistant identifies config entries and
registry entries by integration domain, so that entry no longer loads after the
rename:

1. Delete the old **Ampere.IQ SmartBox Home Assistant** entry in
   *Settings → Devices & services*.
2. Add **KiwiOS** again with the same URL.

Entity IDs may get a `_2` suffix when you re-add the integration, because the
registry keys are scoped to the integration domain.
