# Measy TikTok slideshow bot: design

Date: 2026-10-08. Status: approved in chat, awaiting review of this written spec.

## Goal

Every morning, without anyone touching a computer, a ready-made TikTok photo slideshow for the
Measy account lands in the owner's TikTok inbox as a draft. The owner opens the notification, adds a
sound and posts. The bot never posts publicly by itself.

## The slideshow (7 slides, always in this order)

1. **Cover**: a freshly AI-generated photo of an Aldi storefront (no text in the generated image),
   with the day's hook drawn on it in a white rounded TikTok-style caption box and `>>>>` under it.
   An optional second, smaller box holds a sub-line (e.g. "Big flavour, tiny budget 👀").
2-6. **Five recipe images** from the owner's 157 pre-made recipe cards.
7. **Promo slide** for the Measy app, rotated from a `promo/` folder.

## Decisions made with the owner

| Topic | Decision |
|---|---|
| Delivery | TikTok drafts (Content Posting API, `MEDIA_UPLOAD` mode); the owner adds a sound and posts |
| Cover | Fresh AI image every day |
| Image generator | OpenAI GPT Image (default model `gpt-image-2`, 1024x1536, quality `medium`, about 5¢; configurable) |
| Hook + caption | Written daily by an OpenAI text model in the owner's style; saved fallback list if the API fails |
| Where it runs | GitHub Actions (free), repo `tomovids/measy-tiktok-bot` (public, so GitHub Pages is free) |
| Approach | The owner's own TikTok developer app; images served to TikTok from GitHub Pages |
| Language | British English, prices in £ (this is the owner's UK audience) |
| AI label | TikTok's AI-generated flag turned on by default (the cover is a realistic AI image); `config.toml` can turn it off |

## Daily run

The workflow runs on a schedule at the posting time (default 07:30 Europe/London) and can also be
started by hand (`workflow_dispatch`). GitHub cron is UTC, so it is scheduled at 06:30 and 07:30 UTC;
the bot only proceeds when London time is at or past the posting time and today has no successful
post in the history. A workflow `concurrency` group stops two runs overlapping.

1. **Pick 5 recipes** (`measybot/picker.py`) from `data/recipes.json`:
   - never the same dish twice in one post (dishes are grouped: the three peri peri pasta images are one dish);
   - dishes rotate least-recently-used first (never-used dishes before anything else), so every dish
     comes round once before dishes repeat (63 dishes = about every 13 days); a random spread of
     `jitter_days` (4) stops the same five dishes always travelling together. (Changed during the build:
     rotating by *image* clashed with the dish cooldown, because one dish has up to 9 images.)
   - within a dish, the image shown longest ago is used, so the images of a dish take turns;
   - a dish is never repeated within `dish_cooldown_days` (7); if the rules leave fewer than 5
     candidates the variety rules give way first, then the cooldown one day at a time;
   - variety: at most 3 recipes with the same main ingredient (half the dishes are chicken, so 2 made the
     chicken dishes come round less often), at most 2 with the same base, and no two dishes whose names
     mostly share words (e.g. sticky BBQ chicken / beef rice bowls);
   - the 21 cards priced in US dollars are left out (`skip_dollar_cards`);
   - choices are random but seeded by the date, so a dry run for a given date is reproducible;
   - promo images are never picked as recipes.
2. **Write the words** (`measybot/writer.py`) with the OpenAI text model (configurable). Input: the 5
   dish names with any known prices and cook times, the owner's past hooks (`data/hook_examples.txt`,
   best performers marked), and the last 30 hooks used. Output (JSON): `hook`, optional `subline`,
   `caption`, `scene` (time of day, weather, camera angle for the cover). Checks before accepting:
   - hook at most 60 characters, ends with 1-2 emoji, mentions Aldi;
   - any number of dinners/meals stated must be 5;
   - **claims must be true for the picked recipes**: a £ amount ("for under £15", "if I had £10") is only
     allowed when all 5 cards show a cost and their total is at or under it; "ready in N minutes" only
     when all 5 show a cook time of N or less. Otherwise the prompt tells the model to make no such claim;
   - not a repeat of the last 30 hooks.
   A failed check retries (up to 3 times), then falls back to `data/hooks_fallback.txt` and a caption template.
3. **Make the cover** (`measybot/cover.py`):
   - generate the background with GPT Image from the prompt template in `config.toml` filled with the
     day's `scene` (a realistic UK Aldi store front, blue sky or the day's weather, no added text);
   - centre-crop 1024x1536 to 9:16 and resize to 1080x1920;
   - draw the hook in a white rounded box (TikTok Sans, black, auto-shrinks to fit at most 3 lines,
     about 86% of the width, centred a little above the middle), the optional sub-line in a second
     smaller box, and `>>>>` in white with a dark outline under it; emoji drawn in colour from Noto Color Emoji;
   - save as JPEG (quality 92); the first 10 generated backgrounds are kept in `state/backgrounds/` as spares;
   - if image generation fails, reuse a spare background with the new text.
4. **Promo slide**: the next image in `images/promo/` (rotating in file-name order).
5. **Stage the slides** (`measybot/stage.py`) into `site/p/<YYYY-MM-DD>/01.jpg ... 07.<ext>`. Recipe and
   promo images are copied as they are when they are JPEG/WebP, at most 1080x1920 and under 20 MB;
   anything else is resized/converted to JPEG (12 cards are 1086-1145 px wide and get resized). The
   run's choices are written to `site/p/<date>/post.json` for the next step. `site/p/` is not committed:
   it travels to the next job as a workflow artifact, so the repo doesn't grow by 2 MB a day.
6. **Publish to GitHub Pages**: the workflow deploys `site/` with `actions/upload-pages-artifact` +
   `actions/deploy-pages`. The bot then waits (up to 10 minutes) until every slide URL answers 200
   with an image content type.
7. **Send to TikTok** (`measybot/tiktok.py`):
   - refresh the access token from the stored refresh token;
   - `POST https://open.tiktokapis.com/v2/post/publish/content/init/` with `media_type: PHOTO`,
     `post_mode: MEDIA_UPLOAD`, `post_info: {title: hook (max 90), description: caption}`,
     `source_info: {source: PULL_FROM_URL, photo_images: [7 URLs], photo_cover_index: 0}` and the AI flag;
   - poll `POST /v2/post/publish/status/fetch/` every 10 s (up to 10 minutes) until
     `SEND_TO_USER_INBOX` (success) or `FAILED` (report `fail_reason`).
8. **Record it** (`measybot/history.py`): append to `state/history.json` (date, image files, dish
   groups, hook, sub-line, caption, background file, promo file, publish id, status). The workflow
   commits `state/` back to the repo. Images count as used **only** once TikTok accepted the draft.

The caption: one intro line, the 5 dishes as a numbered list, "Full recipes on the Measy app (link in
bio) 📲", then the hashtags from `config.toml`.

## Project layout

```
measy-tiktok-bot/
  measybot/            __main__.py (CLI), config.py, catalogue.py, picker.py, writer.py, openai_api.py,
                       cover.py, stage.py, pipeline.py, tiktok.py, tokens.py, history.py
  images/recipes/      the 157 recipe images (file names kept)
  images/promo/        promo slides (starts with the "Plan tasty meals made easy" slide)
  fonts/               TikTokSans (OFL), NotoColorEmoji (OFL), with licence files
  data/recipes.json    catalogue: file, dish, group, protein, base, cost_total, serves, time_mins, kind
  data/hook_examples.txt, data/hooks_fallback.txt
  config.toml          post time, timezone, hashtags, models, image quality, prompt template, AI flag, cooldown
                       (TOML instead of YAML: Python reads it without an extra package)
  state/               history.json, tiktok_token.enc, backgrounds/
  site/                GitHub Pages: index.html, auth.html, TikTok verification file, p/<date>/ (not committed)
  tests/               pytest
  .github/workflows/daily.yml, site.yml (publishes site/ when it changes, e.g. the verification file)
  .env.example         local secrets for test runs (.env is git-ignored)
  SETUP.md             click-by-click setup guide
```

CLI: `python -m measybot build` (steps 1-5; prints "nothing to do" if today is done),
`python -m measybot send` (steps 6-8 after the deploy), `python -m measybot dry-run --days N --out DIR`
(builds N days of slides locally, no Pages/TikTok, does not touch history),
`python -m measybot authorize` (one-time TikTok login), `python -m measybot status` (history summary).

Workflow `daily.yml`, two jobs so skipped runs don't create Pages deployments:
`build` (checkout, Python 3.12 + requirements, `build`; if it built: pack `site/p` + `state` as an artifact
and upload `site/` as the Pages artifact) and `send` (only if built; `github-pages` environment: unpack,
`actions/deploy-pages`, `send`, then always commit `state/` with the built-in `GITHUB_TOKEN`).

## TikTok login

- The owner's TikTok developer app (sandbox first) with Login Kit + Content Posting API, scopes
  `user.info.basic` and `video.upload`, redirect URI `https://tomovids.github.io/measy-tiktok-bot/auth.html`
  (a static page that shows the returned `code` to copy).
- `python -m measybot authorize` (run once on the owner's PC) opens the TikTok consent page, takes the
  pasted code and exchanges it for tokens.
- Tokens are stored as `state/tiktok_token.enc`, encrypted with Fernet; the key is the GitHub secret
  `TOKEN_KEY`. After every refresh the new tokens are written back and committed. Refresh tokens last
  about a year, so the owner may need to run `authorize` again roughly yearly; the bot says so when it happens.
- Image URLs must be on an address the app has verified: the URL prefix
  `https://tomovids.github.io/measy-tiktok-bot/` (verification file placed in `site/`). Fallback if TikTok
  won't accept it: a `getmeasy.com` subdomain pointed at GitHub Pages and verified by DNS.

Secrets: `OPENAI_API_KEY`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TOKEN_KEY`. The owner sets
them with `gh secret set` (the assistant never sees them).

## One-time setup

1. (Assistant) Create the repo, enable Pages (source: GitHub Actions), copy in images and fonts.
2. (Assistant) Build `data/recipes.json` by looking at every image; mark promo images; the owner can
   correct dish names.
3. (Owner) Add the OpenAI key as a secret (and to a local `.env` for dry runs).
4. (Owner, following SETUP.md) Create the TikTok developer app, add the products/scopes/redirect URI,
   verify the URL prefix (the assistant commits the verification file), add their account as a sandbox
   target user, set the client key/secret secrets.
5. (Owner + assistant) Run `authorize`, set `TOKEN_KEY`, commit the encrypted token.

## Errors

- Any failure makes the run fail (red on GitHub; GitHub emails the owner) with a plain message in the log.
- OpenAI calls retry 3 times, then fall back (saved hooks / an old background). TikTok calls retry on
  429 and 5xx with backoff.
- `spam_risk_too_many_pending_share` (more than 5 drafts waiting in 24 h): stop and tell the owner to
  post or delete waiting drafts.
- `scope_not_authorized`, `access_token_invalid`, an expired refresh token: stop and say to re-run `authorize`.
- `url_ownership_unverified`: stop and point to the verification step.
- Nothing is marked used unless TikTok accepted the draft, so a failed day costs no recipes (it may
  cost one image generation).
- GitHub may start scheduled runs late (15-60 min); fine for drafts. The daily commit keeps the repo
  active so GitHub never pauses the schedule (it pauses after 60 days without activity).

## Testing

- pytest: the picker rules (no repeated dish in a post, every image used before any repeat across a
  simulated 60 days, cooldown, variety caps, promo never picked, deterministic for a date); the claim
  checks in the writer (with the OpenAI call stubbed); cover layout (long hooks wrap and fit, emoji
  render, output is 1080x1920 JPEG); staging (sizes/formats, cleanup); history and token round trip;
  TikTok request bodies and status handling against recorded responses.
- `dry-run --days 3` locally: the owner reviews the slides and captions before anything goes to TikTok.
- One real draft to the owner's account: confirms the whole chain and answers the open question below.

## Open question

TikTok's docs say content from apps it hasn't reviewed is private-only. That is stated for direct
posting; it is not clear whether drafts (`MEDIA_UPLOAD`) from a sandbox app work. The first real test
answers it. If drafts are blocked: apply for TikTok's app review (needs a privacy policy URL, terms URL
and a short demo video; getmeasy.com may already have the first two), or replace `tiktok.py` with a
paid posting service that supports TikTok drafts. Nothing else changes either way.

## Out of scope

Choosing music (TikTok's API can't set a sound on a draft), posting publicly without review, analytics,
several accounts, editing the recipe images, generating new recipe cards.

## Build order

1. Repo skeleton, config, fonts, images, `.env.example`, `.gitignore`.
2. Catalogue (`data/recipes.json`) + picker + tests.
3. Writer + tests (stubbed OpenAI).
4. Cover renderer + tests; image generation.
5. Staging + `dry-run`; show the owner 3 days of slides.
6. TikTok auth/tokens/send + tests; `site/` pages; workflow.
7. SETUP.md; owner setup; first real draft.
