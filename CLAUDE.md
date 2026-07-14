# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Versioning conventions (bump `PluginVersion` in `Info.plist`, tag and push together) are defined in the parent `../CLAUDE.md` and apply here.

## What this is

SMTPd is a plugin for the [Indigo](https://www.indigodomo.com/) home automation system. It runs a small SMTP server inside Indigo so that other devices/apps on the local network can send email that Indigo consumes. Received messages are exposed to Indigo as variables and fire a trigger.

There is no build step, no test suite, and no lint config. The plugin is a macOS bundle (`SMTPd.indigoPlugin/`) that Indigo loads directly; "running" it means double-clicking the bundle in Indigo (or restarting the plugin from the Indigo UI). All Python runs inside Indigo's embedded interpreter — you cannot execute `plugin.py` standalone because `import indigo` only resolves inside the Indigo server process.

## Architecture

Everything lives in `SMTPd.indigoPlugin/Contents/Server Plugin/plugin.py`. Indigo instantiates `Plugin` and calls its lifecycle methods (`startup`, `shutdown`, `triggerStartProcessing`, `validatePrefsConfigUi`, `closedPrefsConfigUi`, …). The mapping is:

- **`Plugin.startup`** creates/locates an Indigo variable folder named `SMTPd` (storing its id in `pluginPrefs["folderId"]`), then starts an `aiosmtpd` `Controller` bound to all interfaces on the configured port, wiring in `Handler` and `Authenticator`. `shutdown` stops the controller.
- **`Handler.handle_DATA`** parses each inbound message with the stdlib `email` package, decodes RFC 2047 headers, extracts the first body part (only the first alternative for multipart), and writes four Indigo variables via `updateVar`: `smtpd_messageTo`, `smtpd_messageFrom`, `smtpd_messageSubject`, `smtpd_messageText`.
- **`Authenticator`** enforces LOGIN/PLAIN auth against a single username/password from prefs. `auth_require_tls=False`, so this is plaintext auth on the LAN only.
- **Triggers**: `Events.xml` defines the `messageReceived` trigger. `triggerCheck` executes any registered `messageReceived` triggers. Note `handle_DATA` currently updates the variables but does not itself invoke `triggerCheck`.

Config fields (`PluginConfig.xml`) map directly to `pluginPrefs` keys: `smtpPort`, `smtpUser`, `smtpPassword`, `logLevel`. `validatePrefsConfigUi` rejects ports below 1024.

## Dependencies

`requirements.txt` pins `aiosmtpd==1.4.5`. Indigo bundles/installs plugin Python dependencies; the version is significant because aiosmtpd's API (e.g. `AuthResult`, `LoginPassword`, `decode_data`) has shifted across releases, and past commits were driven by aiosmtpd/asyncio upgrades.

## Requirements

Minimum Indigo version 2022.1. `Info.plist` declares `ServerApiVersion` 3.4.
