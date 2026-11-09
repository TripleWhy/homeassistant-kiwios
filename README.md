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
| EKD Ampere.IQ Smartbox | `ampere_iq_smartbox` | A [virtual integration](https://developers.home-assistant.io/docs/creating_integration_manifest#virtual-integration): a manifest-only alias that points at `kiwios`, so the product can be listed under its sales name. |

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

Every channel the device exposes through `/rest/things` becomes a sensor. Each
measurement that carries a device-side timestamp also gets a matching
`… Timestamp` sensor, which is disabled by default; enable it in the entity
settings if you need to know when a value was measured.

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
