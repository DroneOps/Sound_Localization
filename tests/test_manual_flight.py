import time

import pytest

from soundloc.fake_tello import FakeTello
from soundloc.manual_flight import ManualFlight, split_keys
from soundloc.session import Session
from soundloc.tello import TelloClient


def test_arrow_keys_are_not_taken_as_escape():
    assert split_keys("w\x1b[Aa") == ["w", "ESPECIAL", "a"]
    assert split_keys("\x1b[1;5C\x1b[3~q") == ["ESPECIAL", "ESPECIAL", "q"]
    assert split_keys("\x1bOq") == ["ESPECIAL"]  # el 1 del teclado numérico con Bloq Num apagado
    assert split_keys("\x1b") == ["ESC"]
    assert split_keys("1\n") == ["1", "ENTER"]


@pytest.fixture
def flight(tmp_path):
    fake = FakeTello(cmd_port=28911, state_port=28912, speed_mps=2.0)
    fake.start()
    client = TelloClient("127.0.0.1", 28911, 28912, local_port=0)
    client.start()
    client.connect()
    session = Session(tmp_path, "prueba_manual")
    deadline = time.monotonic() + 2
    while client.state()[1] > 0.5 and time.monotonic() < deadline:
        time.sleep(0.05)
    f = ManualFlight(client, session, plan=[1.0, 1.8], speed=30, t_start=time.monotonic() - 10,
                     log=lambda message: None)
    yield fake, f, session
    client.close()
    fake.stop()


def ticks(f, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        f.tick()
        time.sleep(0.1)


def test_a_nudge_moves_the_drone_and_a_hover_is_marked(flight):
    fake, f, session = flight
    f.handle_key("q")
    assert f.flying
    x0 = fake.x
    f.handle_key("w")
    ticks(f, 0.5)
    assert fake.x > x0 + 0.03  # el empujón hacia adelante lo movió
    f.handle_key("1")
    ticks(f, 0.6)
    f.handle_key("a")  # una corrección durante el hover
    ticks(f, 0.4)
    f.handle_key("1")
    f.handle_key("e")
    assert not f.flying and not fake.motors
    hovers = [s for s in session.segments if s["tipo"] == "hover"]
    assert len(hovers) == 1 and hovers[0]["distancia_m"] == 1.0
    assert f.hovers[0]["correcciones"] == 1
    assert any(s["etiqueta"] == "ambiente_inicio" for s in session.segments)


def test_enter_cuts_the_motors(flight):
    fake, f, _ = flight
    f.handle_key("q")
    f.handle_key("ENTER")
    assert f.done and f.emergency_fired and not fake.motors


def test_takeoff_waits_for_the_ambient_measurement(flight):
    fake, f, _ = flight
    f.t_start = time.monotonic()
    f.handle_key("q")
    assert not f.flying and not fake.motors
