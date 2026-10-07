# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-07

First release.

### Added

- Lighting effects for every zone: Static, Breathing, Spectrum Cycle, Rainbow
  Wave, Colour Wave, Marquee, Blink and Temperature, with colours, speed,
  direction and brightness, and a live preview.
- Effects handed to devices that can play them, and drawn by Prism in sync
  everywhere else.
- A native Corsair Commander Pro driver that runs hardware effects across
  every LED on a channel and sets fan duties.
- Corsair Hydro Platinum support through liquidctl: pump LEDs, radiator fans,
  pump mode and coolant temperature.
- RAM, GPU and motherboard lighting through OpenRGB's SDK server, started
  hidden when needed.
- Fan curves against any temperature with draggable points and presets, fixed
  speeds, a speed floor, failsafe speed and a safe speed on exit.
- Profiles with copy, rename, delete, import and export, and first-run
  profiles fitted to the connected hardware.
- Rules that switch profile while a reading is high or a program is running,
  with settle times and priorities.
- A dashboard of live readings, fan speeds and device status.
- A tray icon for switching profiles and pausing rules, start at login, and a
  single running copy.
