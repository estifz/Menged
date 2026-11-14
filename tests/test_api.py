"""The mobile-app REST adapter, driven through FastAPI with the same engine."""

from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import DEST, START, lat_at


async def test_app_flow(db, channel, scenario):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/health")).json() == {"ok": True}
        assert (await c.get("/v1/me/settings")).status_code == 401

        r = await c.post("/v1/devices", json={"language": "am"})
        assert r.status_code == 200
        h = {"Authorization": f"Bearer {r.json()['token']}"}

        assert (await c.get("/v1/me/settings", headers=h)).json()["language"] == "am"
        r = await c.put("/v1/me/settings", headers=h, json={"language": "en", "voice_on": False, "alert_level": "chatty"})
        assert r.status_code == 200 and r.json()["alert_level"] == "chatty"

        r = await c.post(
            "/v1/trips",
            headers=h,
            json={"destination": {"lat": DEST[0], "lon": DEST[1], "name": "Bole"}, "start": {"lat": START[0], "lon": START[1]}},
        )
        assert r.status_code == 201, r.text
        trip = r.json()
        assert trip["status"] == "routed" and trip["distance_m"] == 6000 and trip["route_line"]
        tid = trip["id"]

        r = await c.post(
            f"/v1/trips/{tid}/locations",
            headers=h,
            json={"points": [{"lat": lat_at(0), "lon": START[1], "accuracy_m": 8}, {"lat": lat_at(150), "lon": START[1]}]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["trip"]["status"] == "active"
        assert [m["type"] for m in body["messages"]] == ["tracking_started"]

        msgs = (await c.get(f"/v1/trips/{tid}/messages", headers=h, params={"since": 0})).json()
        assert [m["type"] for m in msgs] == ["trip_routed", "tracking_started"]
        last_id = msgs[-1]["id"]
        assert (await c.get(f"/v1/trips/{tid}/messages", headers=h, params={"since": last_id})).json() == []

        r = await c.get("/v1/where", headers=h, params={"lat": lat_at(300), "lon": START[1]})
        assert "Churchill Avenue" in r.json()["text"]

        r = await c.post(f"/v1/trips/{tid}/end", headers=h)
        assert r.json()["status"] == "ended"
        assert (await c.get(f"/v1/trips/{tid}", headers=h)).json()["status"] == "ended"

        # Another device cannot see this trip.
        other = (await c.post("/v1/devices", json={})).json()["token"]
        r = await c.get(f"/v1/trips/{tid}", headers={"Authorization": f"Bearer {other}"})
        assert r.status_code == 404


async def test_trip_by_query_uses_search(db, channel, scenario):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = (await c.post("/v1/devices", json={})).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.get("/v1/places/search", headers=h, params={"q": "edna mall"})
        assert r.json()[0]["name"] == "Edna Mall"
        r = await c.post("/v1/trips", headers=h, json={"destination_query": "edna mall"})
        assert r.status_code == 201 and r.json()["dest_name"] == "Edna Mall" and r.json()["status"] == "created"
        assert (await c.post("/v1/trips", headers=h, json={})).status_code == 422
