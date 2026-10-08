import pytest
from PIL import Image

from measybot import card
from measybot.card import CardRecipe

ENTRY = {
    "title": "Sticky Hoisin Beef Flatbreads", "subtitle": "Quick, easy and packed with flavour!",
    "serves": 4, "prep_mins": 10, "cook_mins": 15, "calories": 520,
    "ingredients": [{"item": "beef mince", "qty": "500g", "price": 2.99},
                    {"item": "flatbreads", "qty": "4", "price": 0.85},
                    {"item": "red onion", "qty": "1", "price": 0.69},
                    {"item": "hoisin sauce", "qty": "200g", "price": 1.09},
                    {"item": "salt & pepper", "qty": None, "price": 0.05}],
    "method": [{"title": "Cook the beef", "text": "Fry the mince until browned."},
               {"title": "Make the sauce", "text": "Stir in the hoisin and simmer until sticky."},
               {"title": "Warm the flatbreads", "text": "Heat in a dry pan for a minute."},
               {"title": "Assemble", "text": "Top with the beef and onion."}],
    "tip": "Swap the beef for Quorn mince for a cheaper option.",
}
PHOTO = Image.new("RGB", (1536, 1024), (180, 120, 70))


def test_total_is_the_sum_of_the_ingredients():
    r = CardRecipe.from_dict(ENTRY)
    assert r.total == 5.67 and r.per_serving == 1.42


def test_no_total_when_a_price_is_missing():
    d = dict(ENTRY, ingredients=ENTRY["ingredients"] + [{"item": "coriander", "qty": None, "price": None}])
    assert CardRecipe.from_dict(d).total is None


def test_render_size():
    img = card.render(CardRecipe.from_dict(ENTRY), PHOTO)
    assert img.size == (1080, 1920) and img.mode == "RGB"


def test_short_recipe_gets_the_biggest_photo():
    # with little text the layout uses the tallest photo (760 px): the photo colour fills that band
    img = card.render(CardRecipe.from_dict(ENTRY), PHOTO)
    column = [img.getpixel((540, y)) for y in range(0, 1920, 10)]
    photo_rows = sum(1 for p in column if p == (180, 120, 70))
    assert photo_rows * 10 >= 700


def test_too_long_recipe_raises():
    d = dict(ENTRY, method=[{"title": "Step", "text": "word " * 60}] * 5)
    with pytest.raises(ValueError):
        card.render(CardRecipe.from_dict(d), PHOTO)
