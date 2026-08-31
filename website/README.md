# TikTok TechJam Website

Product narrative and deterministic conversational-shopping demo for the TikTok TechJam project.

## Run locally

```bash
npm install
npm run dev
```

Open the local URL printed by Vite. The main routes are:

- `/` — Product story and evaluation dashboard
- `/demo` — Conversational shopping demo

## Production build

```bash
npm run check
npm run build
```

The production output is generated in `dist/`.

## Optional chat API

The Demo runs as a deterministic local mock by default. To connect a compatible chat API, set:

```bash
VITE_CHAT_API_URL=https://example.com/chat
```
