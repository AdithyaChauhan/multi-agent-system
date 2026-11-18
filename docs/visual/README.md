# Visual explainer

`agent-flow.html` is the source of the scroll-driven 3D explainer, published as a claude.ai artifact:
https://claude.ai/artifact/2ZtU89shqw2C7Jqq56nGgF (private until it's shared from the page's Share menu).

It follows one chat message through the browser, FastAPI, the router, an agent, Groq and Postgres. There are six stories (refine a product search, track an order, report a damaged item, cancel an order, report a safety risk, ask while signed out), and a Today / Proposed switch that shows the Phase 1–4 design.

## Updating it at project completion (Phase 5)
- Steps that are now built lose their "Proposed" tag. Remove the "not built yet" wording, and make the built design the default (or drop the switch).
- Replace illustrative numbers with measured ones: tokens per turn, recall@5, p95 latency.
- Check every step's file and function reference (`ref`) against the code.
- Republish to the same link: ask Claude to read the artifact at the URL above, then publish this file to that URL.

## Notes
- This is artifact source: it has no `<html>`, `<head>` or `<body>` wrapper, because the artifact platform adds one. To host it anywhere else, such as the portfolio, wrap it in a normal HTML document with a doctype, a charset and a viewport meta tag.
- It loads three.js r128 from cdnjs and fonts from Google Fonts. Story content is in the `STORIES` array near the top of the script.
- Design notes: one idea per screen, a dark full-screen scene, large serif headlines, short copy, labels only on the active stop, and a minimal HUD in the corners. An earlier, denser version (side panels, every node labelled, legend, controls bar) was rejected as cluttered. Keep it sparse when editing.
