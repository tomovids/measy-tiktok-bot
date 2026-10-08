# Measy TikTok slideshow bot

Every morning a GitHub Action makes a 7-slide TikTok photo slideshow and drops it into the Measy
account's TikTok drafts. Open the notification, add a sound, post.

1. **Cover:** a fresh AI picture of an Aldi store front (OpenAI GPT Image) with the day's hook in
   TikTok-style white caption boxes and `>>>>`.
2. **Slides 2-6:** five recipe cards from `images/recipes/`, picked so every dish comes round evenly,
   never the same dish twice in a post, a mix of proteins and bases, and the dollar-priced cards left out.
3. **Slide 7:** the next promo slide from `images/promo/` (drop more in to rotate them).

The hook, an optional second line and the caption are written by OpenAI in the style of the account's
best posts (`data/hook_examples.txt`). Claims are checked against the cards: "under £15" only when the
five cards really add up to £15 or less, "ready in 20 minutes" only when every card says so.

Setup: see [SETUP.md](SETUP.md). Design: [docs/superpowers/specs](docs/superpowers/specs).

## Commands

```
python -m measybot dry-run --days 3     # build 3 days of slides into out\ (nothing is sent)
python -m measybot status               # recent posts and the TikTok login's expiry
python -m measybot authorize            # log in to TikTok (once a year)
python -m measybot build / send         # what the GitHub Action runs
```

On Windows use `.\.venv\Scripts\python.exe` instead of `python`. Tests: `.\.venv\Scripts\python.exe -m pytest`.

## Changing things

- Posting time, hashtags, image quality, emoji, variety rules: `config.toml`.
- Recipe names, prices and groups: `data/recipes.json` (one entry per image; images with the same
  `group` are the same dish). Add new recipe images to `images/recipes/` together with an entry.
- Saved hooks for days the AI writer is down: `data/hooks_fallback.txt`.
- What has been posted: `state/history.json` (written by the bot).

Fonts: TikTok Sans and Noto Color Emoji, both under the SIL Open Font License (licences in `fonts/`).
