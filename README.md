# BAY-S Lead Radar V5.2

North Cyprus foreign-property-buyer radar.

V5.2 focuses on real purchase intent, uses Exa for public web discovery, scans relevant Telegram groups candidate-first instead of relying on the legacy scorer, filters seller/listing copy, rentals and non-property purchases, and sends accepted HOT/WARM leads to Telegram.

Key change: every recent message in relevant North Cyprus / Cyprus groups can reach the strict buyer gate. A message no longer has to be pre-approved by the old `tg_score()` logic before V5 can inspect it.

The feature branch is test-first. Production remains unchanged until the draft PR is reviewed and merged.
