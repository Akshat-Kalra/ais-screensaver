from datetime import datetime, timezone

import pytest

from aissaver import tables
from aissaver.aisstream import clean_text, eta_to_unix, handle_message
from aissaver.store import Store

T0 = 1_790_000_000.0  # fixed "now"
MMSI = 563012345


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    yield s
    s.close()


def position(mmsi=MMSI, lat=1.25, lon=103.9, sog=12.3, cog=88.0, hdg=87, nav=0, kind="PositionReport"):
    body = {"UserID": mmsi, "Latitude": lat, "Longitude": lon, "Sog": sog, "Cog": cog,
            "TrueHeading": hdg, "Valid": True}
    if kind == "PositionReport":
        body["NavigationalStatus"] = nav
    return {"MessageType": kind, "MetaData": {"MMSI": mmsi, "ShipName": "EVER TEST@@@@  "},
            "Message": {kind: body}}


def test_position_report(store):
    assert handle_message(store, position(), T0) == "PositionReport"
    v = store.vessels[MMSI]
    assert (v.lat, v.lon, v.sog, v.cog, v.heading, v.nav_status) == (1.25, 103.9, 12.3, 88.0, 87, 0)
    assert v.region == "singapore"
    assert v.name == "EVER TEST"  # from metadata until static data arrives


def test_sentinels_are_dropped(store):
    assert handle_message(store, position(lat=91, lon=181), T0) is None
    assert handle_message(store, position(lat=0, lon=0), T0) is None
    handle_message(store, position(sog=102.3, cog=360, hdg=511), T0)
    v = store.vessels[MMSI]
    assert v.sog is None and v.cog is None and v.heading is None


def test_non_ship_mmsis_ignored(store):
    assert handle_message(store, position(mmsi=992351234), T0) is None  # aid to navigation
    assert handle_message(store, position(mmsi=2320001), T0) is None  # base station (00MID...)


def test_class_b_position(store):
    msg = position(kind="StandardClassBPositionReport")
    assert handle_message(store, msg, T0) == "StandardClassBPositionReport"
    assert store.vessels[MMSI].nav_status is None


def test_ship_static_data(store):
    msg = {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": MMSI},
        "Message": {"ShipStaticData": {
            "UserID": MMSI, "Valid": True, "Name": "EVER GIVEN@@@@@@@@@@", "CallSign": "H3RC@@@",
            "ImoNumber": 9811000, "Type": 71, "Dimension": {"A": 300, "B": 100, "C": 30, "D": 29},
            "MaximumStaticDraught": 14.5, "Destination": "NL RTM@@@@@@@@@@@@@",
            "Eta": {"Month": 10, "Day": 25, "Hour": 6, "Minute": 0},
        }},
    }
    assert handle_message(store, msg, T0) == "ShipStaticData"
    v = store.vessels[MMSI]
    assert (v.name, v.callsign, v.imo, v.ship_type) == ("EVER GIVEN", "H3RC", 9811000, 71)
    assert (v.length, v.beam, v.draught, v.destination) == (400, 59, 14.5, "NL RTM")
    assert v.eta is not None
    assert tables.ship_type_info(v.ship_type) == ("Cargo · Hazard A", "cargo")


def test_static_data_report_parts(store):
    part_a = {"MessageType": "StaticDataReport", "MetaData": {"MMSI": MMSI}, "Message": {"StaticDataReport": {
        "UserID": MMSI, "Valid": True, "PartNumber": False,
        "ReportA": {"Valid": True, "Name": "SEA BREEZE@@@@"}, "ReportB": {"Valid": False}}}}
    part_b = {"MessageType": "StaticDataReport", "MetaData": {"MMSI": MMSI}, "Message": {"StaticDataReport": {
        "UserID": MMSI, "Valid": True, "PartNumber": True, "ReportA": {"Valid": False},
        "ReportB": {"Valid": True, "CallSign": "VG1234", "ShipType": 36,
                    "Dimension": {"A": 8, "B": 4, "C": 2, "D": 2}}}}}
    handle_message(store, part_a, T0)
    handle_message(store, part_b, T0)
    v = store.vessels[MMSI]
    assert (v.name, v.callsign, v.ship_type, v.length, v.beam) == ("SEA BREEZE", "VG1234", 36, 12, 4)


def test_static_does_not_erase_known_fields(store):
    store.update_static(MMSI, name="KNOWN", destination="SGSIN")
    store.update_static(MMSI, name=None, destination="")
    assert store.vessels[MMSI].name == "KNOWN"
    assert store.vessels[MMSI].destination == "SGSIN"


def test_downsampling(store):
    stored = []
    for i in range(20):  # one report every 10s for 200s, steady course
        stored.append(store.update_position(MMSI, 1.25, 103.9 + i * 1e-4, 12.0, 90.0, 90, T0 + i * 10))
    assert stored[0] is True
    assert sum(stored) == 3  # t=0, t=90, t=180
    # sharp turn stores early (>= 10s since last stored point)
    assert store.update_position(MMSI, 1.25, 103.91, 12.0, 140.0, 140, T0 + 200) is True
    # stationary: only every 10 minutes
    t = T0 + 300
    assert store.update_position(MMSI, 1.25, 103.91, 0.1, 140.0, 140, t) is False
    assert store.update_position(MMSI, 1.25, 103.91, 0.1, 140.0, 140, T0 + 200 + 600) is True


def test_out_of_order_ignored(store):
    store.update_position(MMSI, 1.25, 103.9, 12.0, 90.0, 90, T0 + 100)
    assert store.update_position(MMSI, 1.30, 103.95, 12.0, 90.0, 90, T0) is False
    assert store.vessels[MMSI].lat == 1.25


def test_track_roundtrip_and_glitch_filter(store):
    for i in range(10):
        store.update_position(MMSI, 1.25, 103.9 + i * 0.005, 12.0, 90.0, 90, T0 + i * 100)
    store.update_position(MMSI, 5.0, 110.0, 12.0, 90.0, 90, T0 + 1000)  # GPS jump
    store.update_position(MMSI, 1.25, 103.9 + 10 * 0.005, 12.0, 90.0, 90, T0 + 1100)
    store.flush()
    track = store.track(MMSI, T0 - 1)
    assert len(track) == 11
    assert all(lat < 2 for _, lat, _, _ in track)


def test_persistence_reload(tmp_path):
    s = Store(tmp_path / "p.sqlite")
    now = datetime.now(timezone.utc).timestamp()
    s.update_static(MMSI, name="PERSIST")
    s.update_position(MMSI, 1.25, 103.9, 12.0, 90.0, 90, now)
    s.close()
    s2 = Store(tmp_path / "p.sqlite")
    assert s2.vessels[MMSI].name == "PERSIST"
    assert s2.vessels[MMSI].stored_ts == int(now)
    s2.close()


def test_clean_text_and_eta():
    assert clean_text("  MSC  ANNA@@@@ ") == "MSC ANNA"
    assert clean_text("@@@@") is None
    now = datetime(2026, 12, 30, tzinfo=timezone.utc).timestamp()
    eta = eta_to_unix({"Month": 1, "Day": 2, "Hour": 3, "Minute": 4}, now)
    assert datetime.fromtimestamp(eta, timezone.utc).year == 2027  # rolls into next year
    assert eta_to_unix({"Month": 0, "Day": 0, "Hour": 24, "Minute": 60}, now) is None


def test_flags():
    assert tables.flag_for(563012345) == {"code": "SG", "name": "Singapore"}
    assert tables.flag_for(316001234)["code"] == "CA"
    assert tables.flag_for(999999999) is None


def test_pmset_battery():
    from aissaver.system import parse_pmset
    on_ac = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t100%; charged; 0:00 remaining present: true\n"
    assert parse_pmset(on_ac) == {"percent": 100, "charging": False, "plugged": True}
    draining = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t64%; discharging; 5:12 remaining present: true\n"
    assert parse_pmset(draining) == {"percent": 64, "charging": False, "plugged": False}
    charging = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t41%; charging; 1:02 remaining present: true\n"
    assert parse_pmset(charging)["charging"] is True
    assert parse_pmset("Now drawing from 'AC Power'\n") is None  # desktop Mac
