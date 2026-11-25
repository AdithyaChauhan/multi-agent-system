# Visual explainer

`agent-flow.html` is the source of the scroll-driven 3D explainer, published as a claude.ai artifact:
https://claude.ai/artifact/2ZtU89shqw2C7Jqq56nGgF (private until it's shared from the page's Share menu).

It follows one chat message through the browser, FastAPI, the router, an agent, Groq and Postgres, as the code on `main` runs it. There are seven stories: refine a product search (hybrid search and the search loop), ask about the cards (the read-only tool loop), track an order, report a damaged item (the escalation subgraph and the Discord alert), cancel an order (the `interrupt()` pause and resume), report a safety risk (the model plus the safety floor) and ask while signed out. The last screen shows measured numbers, each with how it was measured.

## Updating it
- Republished 2026-11-25 (version 3): the Today / Proposed switch is gone because the proposed design is built, and every step's `ref` was checked against the code. Products, orders and attributes come from `multi_agent_baseline`.
- When the code changes, check each step's `ref` and the numbers on the last screen (`STORIES` near the top of the script, and the `.stats` block).
- Republish to the same link: ask Claude to read the artifact at the URL above, then publish this file to that URL.

## Notes
- This is artifact source: it has no `<html>`, `<head>` or `<body>` wrapper, because the artifact platform adds one. To host it anywhere else, such as the portfolio, wrap it in a normal HTML document with a doctype, a charset and a viewport meta tag.
- It loads three.js r128 from cdnjs and fonts from Google Fonts. Story content is in the `STORIES` array near the top of the script.
- Design notes: one idea per screen, a dark full-screen scene, large serif headlines, short copy, labels only on the active stop, and a minimal HUD in the corners. An earlier, denser version (side panels, every node labelled, legend, controls bar) was rejected as cluttered. Keep it sparse when editing.
