import threading
import time

import pytest

from soundloc.fake_tello import FakeTello
from soundloc.tello import TelloClient, TelloError, parse_state

STATE = ("pitch:1;roll:-2;yaw:3;vgx:0;vgy:0;vgz:0;templ:60;temph:62;tof:98;h:95;bat:87;"
         "baro:101.25;time:12;agx:1.00;agy:-2.00;agz:-999.00;\r\n")


def test_parse_state_converts_types():
    state = parse_state(STATE)
    assert state["tof"] == 98 and isinstance(state["tof"], int)
    assert state["baro"] == pytest.approx(101.25)
    assert state["bat"] == 87


def test_parse_state_keeps_unknown_fields():
    state = parse_state("mid:-1;mpry:0,0,0;tof:10;")
    assert state["mid"] == -1 and state["mpry"] == "0,0,0"


@pytest.fixture
def drone():
    fake = FakeTello(cmd_port=28889, state_port=28890, speed_mps=1.0)
    fake.start()
    client = TelloClient("127.0.0.1", 28889, 28890)
    client.start()
    client.command("command", timeout=2)
    yield fake, client
    client.close()
    fake.stop()


def test_query_and_telemetry(drone):
    fake, client = drone
    assert client.query("battery?") == "90"
    deadline = time.monotonic() + 2
    while client.state()[1] > 0.5 and time.monotonic() < deadline:
        time.sleep(0.05)
    state, age = client.state()
    assert age < 0.5 and state["bat"] == 90


def test_out_of_range_move_is_rejected(drone):
    fake, client = drone
    client.command("takeoff", timeout=5)
    with pytest.raises(TelloError):
        client.command("forward 10", timeout=2)  # el mínimo son 20 cm


def test_emergency_cuts_a_move_short(drone):
    fake, client = drone
    client.command("takeoff", timeout=5)
    start_x = fake.x

    def move():
        try:
            client.command("forward 300", timeout=10)
        except TelloError:
            pass

    mover = threading.Thread(target=move)
    mover.start()
    time.sleep(0.5)
    client.emergency()
    mover.join(timeout=5)
    assert not fake.motors and fake.z == 0.0
    assert fake.x < start_x + 1.5


def test_cancel_stops_waiting_for_a_reply(drone):
    fake, client = drone
    client.command("takeoff", timeout=5)
    client.cancel = threading.Event()
    threading.Timer(0.3, client.cancel.set).start()
    started = time.monotonic()
    with pytest.raises(TelloError):
        client.command("forward 300", timeout=10)
    assert time.monotonic() - started < 2.0
