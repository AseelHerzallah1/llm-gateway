# Portfolio screenshots

Run:

```powershell
python scripts/generate_screenshot_report.py
```

Opens `report.html` in your browser with correct Arabic/Hebrew direction, optional live streaming/cache/metrics sections, and offline PII samples — ready to screenshot.

Requires uvicorn + `GATEWAY_TEST_API_KEY` in `.env` for live sections. PII table always works offline.

For a clean dashboard demo, reset local cache/logs first: `python scripts/reset_demo_state.py` (then restart uvicorn).
