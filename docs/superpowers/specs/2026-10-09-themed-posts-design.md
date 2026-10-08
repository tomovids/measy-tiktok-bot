# Two themed drafts a day, built to spread (stage 2): design

Date: 2026-10-09. Status: approved in chat (themed posts, drafts the owner posts, best chance of going
viral, on-brand, unique ideas every day).

## Schedule
`config.toml [schedule] post_times = ["07:30", "16:30"]` (UK time). The workflow runs at 06:30, 07:30,
15:30 and 16:30 UTC (BST and GMT); each run builds the next draft that is due and not yet sent
(`History.count_on`). Extra test drafts (`--again`) never count. Post folders are `site/p/<date>-<n>`.

## Themes (`data/themes.toml`, `measybot/themes.py`, `measybot/tags.py`)
- Every dish gets tags from its recipe and catalogue entry (cheesy, creamy, sticky, spicy, bbq, garlic,
  loaded, mexican, asian, italian, onepan, fakeaway, chicken/beef/sausage/veggie, pasta/noodles/rice/
  potato/handheld/couscous, quick, under-150, under-2, family, comfort). Hand fixes go in
  `data/dish_tags_extra.toml`.
- A post's theme = a collection (22: anything, cheesy, creamy, sticky, spicy, fakeaway, loaded, mexican,
  asian, italian, chicken, beef, sausage, veggie, pasta, noodles, rice, handheld, quick, under-150,
  under-2, comfort) + an angle (21: payday, tired, no idea, takeaway, repeat, send-to, family, students,
  weekly shop, save, cheap-not-cheap, date night, Friday, Saturday, Sunday reset, Monday, midweek,
  tonight (afternoon only), plan today (morning only), cosy (Oct-Feb), summer (Jun-Aug)).
- Rules: a collection needs 6+ dishes not posted today, rests 4 days; an angle isn't used in the last 3
  posts; a collection + angle pair rests 30 days; day/slot/month limits on angles. Rules relax only when
  nothing else fits. Protein collections lift the protein variety cap, base collections the base cap.
- Dish choice is the stage-1 picker limited to the theme's dishes; cooldown 4 days, never twice in a day.
  The dish with the highest crave score (loaded 3, cheesy/sticky/fakeaway 2, bbq/creamy/spicy 1) leads.

## Hook tournament (`measybot/writer.py`)
- The writer gets `data/brand.md`, the account's past hooks with views, the theme, the weekday and slot,
  the five dishes with their £ a portion and minutes, and the claim rules; it writes 6 candidates, an
  intro and a comment question.
- Each candidate is checked: Aldi mentioned, ends with emoji, <= 64 characters, allowed emoji, 5 dinners,
  money/time claims true for the cards, no avoided words (`[brand] avoid`), second line adds something
  new, never a hook used before, not >= 60% the same words as one of the last 60 hooks. A bad intro or
  question is swapped for a saved one instead of sinking the hooks.
- A judge call scores the survivors harshly (scroll-stopping, relatable, specific, shareable, natural,
  on theme; marks down clumsy wording and repetition) and the best wins. Candidates and scores are kept
  in the history.
- Caption: intro, the numbered dishes, the question, a save line, the CTA, 7 base hashtags + the theme's 2.

## Testing
Unit tests for tags (every collection has 6+ dishes), theme rules (rests, day limits, cap lifting), the
tournament (retry, judge, no reuse, near copies, brand words, swapped intro), the caption and slot
counting; a two-day dry run with real AI.
