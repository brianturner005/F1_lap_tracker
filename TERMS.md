# Terms of Use & Privacy Notice

**Pitwall IQ** is an independent, open-source fan project. It is provided free of charge and carries no warranties. By downloading or using this software you agree to the following.

---

## Disclaimer of Affiliation

**Pitwall IQ is not affiliated with, endorsed by, or associated with Formula 1, Formula One Management Ltd (FOM), the FIA, Electronic Arts Inc. (EA), Codemasters, or any F1 team or driver.**

"F1", "Formula 1", team names, and related marks are trademarks of their respective owners. Any reference to those names in this software is purely for descriptive compatibility purposes (e.g. "compatible with F1 25 UDP telemetry").

---

## What the App Does

Pitwall IQ reads UDP telemetry broadcast by F1 25 (or F1 24/23) on your own machine and displays it in a local browser dashboard. **All lap data is stored locally on your device** in a SQLite database (`f1_laps.db`). Nothing is sent externally unless you explicitly opt in to the features described below.

---

## Data Collection

### Community Leaderboard (opt-in)

If you enable the **SUBMIT PBs** toggle in the dashboard:

- A randomly generated anonymous UUID (created locally on first run, stored in `f1_laps.db`) is sent alongside your lap times.
- Track name, session type, lap time, and tyre compound are submitted to the shared Pitwall IQ backend (hosted on Microsoft Azure).
- No name, email address, IP address, or any other personally identifying information is collected or stored by the backend.
- You can disable submission at any time by toggling **SUBMIT PBs** off. Previously submitted times are not automatically deleted — contact the project maintainer via GitHub Issues to request removal.

### AI Lap Debrief (on request)

When you click **AI DEBRIEF**:

- The current session's lap times, sector splits, track name, and session type are sent to the shared Pitwall IQ backend.
- This data is used solely to generate the debrief and is not retained after the response is returned.
- No personally identifying information is included in the request.

### What is never collected

- Your name, email, or any account credentials
- Your F1 game account or EA account details
- Your device identifiers or IP address
- Any data from outside the Pitwall IQ app

---

## No Warranty

This software is provided **"as is"**, without warranty of any kind, express or implied. The author makes no guarantees regarding accuracy of lap times, compatibility with future game versions, or uninterrupted availability of the shared backend. Use at your own risk.

---

## Shared Backend Availability

The AI debrief and community leaderboard features depend on a shared backend hosted by the project maintainer. This service may be modified, rate-limited, or discontinued at any time without notice. If the backend is unavailable, all core lap tracking features continue to work normally — only the online features are affected.

---

## Changes to These Terms

These terms may be updated at any time. The current version is always available in the project repository. Continued use of the software constitutes acceptance of any updated terms.

---

## Contact

For data removal requests, bug reports, or other queries, open an issue at the project's GitHub repository.

---

*This document is not a substitute for legal advice. If you are uncertain about your obligations or rights, consult a qualified legal professional.*
