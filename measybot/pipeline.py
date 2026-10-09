"""Builds one day's post, and sends a built post to TikTok drafts."""
from __future__ import annotations

import random
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import catalogue, cover, stage, stores, tags, themes, tokens, writer
from .history import History
from .openai_api import OpenAI, OpenAIError
from .picker import pick
from .tiktok import TikTok, TikTokError, wait_for_urls


def build_post(day: date, cfg: dict, hist: History, folder: Path, ai: OpenAI | None,
               ai_image: bool = True, keep_spares: bool = True, save_background: bool = False,
               log=print, extra: bool = False, slot: str = "morning", index: int = 0) -> dict:
    seed = f"{day}/{slot}" + ("/extra" if extra else "")
    store = stores.choose(hist, cfg, random.Random(f"{seed}/store"), index)
    dish_tags = tags.all_tags()
    theme = themes.choose(day, slot, hist, dish_tags, cfg, random.Random(f"{seed}/theme"))
    log(f"Store: {store.name}. Theme: 5 {theme.label} / {theme.angle_text.replace('{store}', store.name)}")
    lead = {g: tags.crave_score(t) for g, t in dish_tags.items()}
    recipes = pick(catalogue.load_recipes(), hist, day, cfg, random.Random(f"{seed}/picker"),
                   allowed=theme.groups, caps_off=theme.caps_off, lead=lead)
    log("Recipes: " + "; ".join(r.dish for r in recipes))

    used = {p["hook"] for p in hist.accepted() if p.get("hook")}
    words = writer.write(recipes, hist.recent_hooks(60), cfg, ai, random.Random(f"{seed}/words"), log,
                         day=day, theme=theme, used=used, slot=slot, store=store)
    log(f"Hook ({words.source}{f', score {words.score}' if words.score else ''}): {words.hook}"
        + (f"  /  {words.subline}" if words.subline else ""))
    caption = writer.caption(words, recipes, cfg, theme, random.Random(f"{seed}/caption"), store)
    words.scene = cover.pick_scene(cfg, random.Random(f"{seed}/scene"))

    background, model, source = _background(day, words.scene, cfg, ai if ai_image else None, log, store)
    if source == "generated" and keep_spares:
        cover.keep_background(background, day, store=store.id)
    sign = cover.find_sign(background, store.id) if source != "placeholder" else None
    slide = cover.render(background, words.hook, words.subline, cfg, random.Random(f"{seed}/cover"),
                         avoid=sign)

    promo = hist.next_promo(catalogue.promo_files())
    meta = {"scene": words.scene, "background": source, "image_model": model, "sign": sign, "extra": extra,
            "slot": slot, "store": store.id, "theme": theme.record(), "question": words.question,
            "hook_score": words.score,
            "hook_candidates": words.candidates,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    post = stage.stage(folder, day, slide, recipes, promo, words, caption, meta)
    if save_background:
        background.save(folder / "background.jpg", "JPEG", quality=90)
    log(f"Built {len(post['slides'])} slides in {folder}")
    return post


def _background(day: date, scene: str, cfg: dict, ai: OpenAI | None, log, store=None):
    if ai is None:
        return cover.placeholder_background(day.isoformat()), "", "placeholder"
    try:
        img, model = cover.generate_background(ai, scene, cfg, store)
        log(f"Cover background generated with {model}")
        return img, model, "generated"
    except OpenAIError as e:
        spare = cover.spare_background(random.Random(f"{day}/spare"), store=store.id if store else "aldi")
        if spare is None:
            raise
        log(f"Image generation failed ({e}); reusing a saved background.")
        return spare, "", "spare"


def send_post(post: dict, cfg: dict, hist: History, tt: TikTok, token_key: str, log=print,
              wait_pages=wait_for_urls) -> str:
    t = cfg["tiktok"]
    urls = [t["pages_base_url"].rstrip("/") + "/" + s for s in post["slides"]]
    record = {k: v for k, v in post.items() if k != "slides"}
    record["urls"] = urls
    try:
        wait_pages(urls, log=log)
        login = tokens.load(token_key)
        login = tt.refresh(login)
        tokens.save(login, token_key)
        days_left = (login["refresh_expires_at"] - time.time()) / 86400
        if days_left < 30:
            log(f"Heads up: the TikTok login runs out in {days_left:.0f} days. "
                f"Run `python -m measybot authorize` again soon.")
        publish_id = tt.send_photo_draft(login["access_token"], urls, post["title"], post["caption"],
                                         t.get("ai_generated", True), log)
        record["publish_id"] = publish_id
        log(f"Sent to TikTok (publish id {publish_id}); waiting for it to reach your inbox...")
        record["status"] = tt.wait_until_sent(login["access_token"], publish_id, log=log)
    except (TikTokError, tokens.TokenError) as e:
        record["status"] = "FAILED"
        record["error"] = str(e)
        raise
    finally:
        record["sent_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        hist.add(record)
        hist.save()
    log("Done: the slideshow is in your TikTok inbox. Open the notification, add a sound and post.")
    return record["status"]
