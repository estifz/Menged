from app.engine.templates import TEXTS, render
from app.services import gazetteer
from app.text.amharic import is_amharic, normalize


def test_amharic_variants_fold_together():
    assert normalize("መድሃኔዓለም") == normalize("መድኃኔአለም") == normalize("መድሀኔዐለም")
    assert normalize("Bole  Medhanialem!") == "bole medhanialem"
    assert is_amharic("ቦሌ") and not is_amharic("Bole")


def test_every_template_has_english_and_renders_in_amharic():
    for key, variants in TEXTS.items():
        assert "en" in variants, key
        params = {"dest": "X", "start": "Y", "km": "1", "minutes": 5, "place": "P", "street": "S", "landmark": "L",
                  "count": 2, "query": "q", "language": "L", "voice": "v", "level": "l", "state": "s",
                  "n": 1, "name": "N", "kind": "k", "meters": 10}
        render(key, "am", **params)
        render(key, "fr", **params)  # unknown language falls back to English


def test_gazetteer_offline_search():
    assert gazetteer.search("edna mall")[0].name == "Edna Mall"
    assert gazetteer.search("መስቀል አደባባይ")[0].name == "Meskel Square"
    assert gazetteer.search("Meskel sqare")[0].name == "Meskel Square"  # typo
    assert gazetteer.search("zzzzqqq") == []
    near = gazetteer.nearest(9.01024, 38.76125, 200)
    assert near and gazetteer.display_name(near[0], "en") == "Meskel Square"


def test_offline_places_along_route_and_food_near():
    pts = [(9.0121, 38.7456), (9.01024, 38.76125)]  # Mexico Square -> Meskel Square
    places = gazetteer.along_route(pts, 200)
    assert places and all(p.kind in ("landmark", "restaurant", "cafe", "fast_food") for p in places)
    food = gazetteer.food_near(9.0121, 38.7456, 500)
    assert all(p.kind in ("restaurant", "cafe", "fast_food") for p in food)
