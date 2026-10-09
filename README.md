# Measy TikTok slideshow bot

Three times a day (07:30, 12:00 and 16:30 UK time) a GitHub Action makes a themed 7-slide TikTok photo slideshow
and drops it into the Measy account's TikTok drafts. Open the notification, add a sound, post.
It runs on GitHub's servers, so your PC can be off. The 07:30 and 16:30 posts are about Aldi; the
12:00 "tester" post rotates through Tesco, Sainsbury's, Asda and Lidl (`config.toml [store_rotation]`).
The recipe cards are the same for every store; the hook, the cover's store front and the hashtags change,
and only Aldi posts make £ claims (the card prices are Aldi prices).

1. **Cover:** a fresh AI picture of the post's supermarket (OpenAI GPT Image) with the day's hook in
   TikTok-style white caption boxes and `>>>>`.
2. **Slides 2-6:** five Measy recipe cards (an AI food photo + the full recipe, drawn by code from
   `data/recipe_library.json`) that fit the post's theme (e.g. "cheesy dinners" + "skint until payday",
   `data/themes.toml`); the most crave-worthy dish leads, dishes rotate evenly, never twice in a day.
3. **Slide 7:** the next promo slide from `images/promo/` (drop more in to rotate them).

The hook is picked in a tournament: OpenAI writes 6 candidates in the style of the account's best posts
(`data/hook_examples.txt`) and the brand guide (`data/brand.md`), rule checks remove the bad ones, and a
second AI pass scores the rest; a hook is never reused. Claims are checked against the cards: "under
£15" only when the five cards really add up to £15 or less, "ready in 20 minutes" only when every card
says so. The caption asks a question (comments) and for a save.

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
