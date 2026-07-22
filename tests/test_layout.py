import math

from app.layout import radial_positions


def test_radial_positions_empty_when_no_satellites():
    assert radial_positions(0.0, 0.0, 0) == []


def test_radial_positions_returns_one_point_per_satellite():
    positions = radial_positions(100.0, 100.0, 4, radius=50.0)
    assert len(positions) == 4


def test_radial_positions_first_point_is_at_angle_zero():
    positions = radial_positions(100.0, 100.0, 4, radius=50.0)
    x, y = positions[0]
    assert math.isclose(x, 150.0, abs_tol=1e-6)
    assert math.isclose(y, 100.0, abs_tol=1e-6)
