from app.geo import COASTLINE_PATHS, INSET_BOX, VIEW_HEIGHT, VIEW_WIDTH, project


def test_project_keeps_relative_north_south_ordering():
    _, sapporo_y = project(43.0621, 141.3544)
    _, fukuoka_y = project(33.5904, 130.4017)
    assert sapporo_y < fukuoka_y


def test_project_keeps_relative_east_west_ordering():
    tokyo_x, _ = project(35.6762, 139.6503)
    fukuoka_x, _ = project(33.5904, 130.4017)
    assert tokyo_x > fukuoka_x


def test_project_stays_within_view_bounds():
    for lat, lon in [(45.551, 141.968), (31.03, 130.686), (33.464, 132.371)]:
        x, y = project(lat, lon)
        assert 0 <= x <= VIEW_WIDTH
        assert 0 <= y <= VIEW_HEIGHT


def test_coastline_paths_are_closed_svg_paths():
    assert len(COASTLINE_PATHS) == 3
    for d in COASTLINE_PATHS:
        assert d.startswith("M ")
        assert d.endswith(" Z")


def test_inset_box_sits_below_the_main_map():
    _, fukuoka_y = project(33.5904, 130.4017)
    assert INSET_BOX["y"] > fukuoka_y
