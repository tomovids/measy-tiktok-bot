# Measy recipe cards (stage 1): design

Date: 2026-10-08. Status: approved in chat (sample cards approved, all 70 dishes requested).

## Why

The owner's feedback on the first drafts: recipe slides must show the meal *and* the recipe ("that's
what people are swiping for"), and the meals must look extremely appealing. The existing images are a mix
of photo posters without recipes, recipe cards with small photos, some priced in dollars, and many with
printed totals that don't match their own ingredient prices. So every recipe slide is now a Measy
recipe card the bot draws itself (style "B": big photo, then the full recipe).

## Pieces

- `data/cards_transcribed.json`: the 67 recipe cards transcribed as printed (title, subtitle, serves,
  times, calories, ingredients with quantities and prices, method, tip, printed totals, notes).
  Three dishes only have a photo poster (creamy tomato potato bake, garlic butter chicken flatbreads,
  sweet chilli beef noodles).
- `measybot/library.py` -> `data/recipe_library.json`: one card-ready recipe per dish, made once by the
  OpenAI text model from the transcription. It keeps the card's ingredients and £ prices (correcting
  only clearly unrealistic ones), prices dollar or unpriced cards at Aldi UK 2025-26 prices, writes
  missing methods and the three missing recipes, cleans ingredient lines (amount + name, no prep words),
  shortens the method to 4-5 steps of at most 130 characters and the tip to 110. Every field it adds or
  changes is listed in the entry's `ai_filled` for review. Each entry is checked (fields present, every
  ingredient priced, 4-5 steps, fits on a card) and retried up to 3 times.
- `measybot/photos.py` -> `images/photos/<dish>-<n>.jpg`: AI food photos (GPT Image, 1536x1024,
  medium), 2 per dish (`[cards] variants`), made once and committed. The prompt (`[cards] photo_prompt`)
  asks for an advertising-quality hero shot (heaped portion, glossy sauce, crispy edges, steam, warm
  side light, soft background), shows only foods from the recipe, melted cheese only when the recipe
  has cheese, never text, hands or packaging. Angles alternate between variants.
- `measybot/card.py`: draws the 1080x1920 card in Measy's colours (cream, deep green, pale green panels):
  logo + "Budget Friendly" badge, title (Fraunces Black, soft), subtitle (Caveat), the photo with a
  price-per-portion badge, a stats row (serves, prep, cook, calories), ingredients with prices (left)
  and numbered method (right), a Measy tip and "Good food. Less stress.". The total is always the sum
  of the ingredient prices. Layout picks the biggest photo (760 down to 520 px tall) at which the recipe
  still fits with text of at least 22 px. Logo: `images/brand/measy-logo.png` when the owner provides
  it; a drawn stand-in until then.
- Posts: `catalogue.load_cards()` turns every dish x photo into a pickable recipe (`file` =
  `card:<dish>-<n>`, layout `card`); `config.toml [picker] layouts = ["card"]` uses only cards;
  `stage.py` draws the card into the slide folder. All 70 dishes are in rotation (no dollar cards left).

## Commands

`python -m measybot library [--only ids]`, `photos [--only ids] [--variants N] [--redo] [--workers N]`,
`cards [--only ids] --out DIR` (previews).

## Costs

One-off: about $7 for 140 photos plus pennies for the recipes. Daily cost unchanged (cards are drawn
by code; only the cover is generated).

## Testing

Unit tests for the card renderer (fits, totals add up), the card loader and the picker on cards;
sample cards reviewed by the owner before generating everything; all cards rendered to a folder and
checked before going live.
