"""Simplified Japan coastline, as (lat, lon) point rings.

Source: Natural Earth 1:110m Cultural Vectors, "Admin 0 - Countries"
dataset (public domain), the feature where NAME == "Japan", from
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson
At this resolution the country geometry already excludes remote islands
(Okinawa is not present in it at all - it's rendered separately via the
`map_inset` flag/box instead of on the main coastline), so no further
filtering of small islands was needed. Coordinates are rounded to 3
decimal places (~100m precision - plenty for a stylized travel map).

Ring 0: Honshu + Kyushu (merged into one ring at this resolution).
Ring 1: Hokkaido.
Ring 2: Shikoku.
"""

JAPAN_COASTLINE_RINGS: list[list[tuple[float, float]]] = [
    [
        (39.181, 141.885), (38.174, 140.959), (37.142, 140.976), (36.344, 140.6),
        (35.843, 140.774), (35.138, 140.253), (34.668, 138.976), (34.606, 137.218),
        (33.465, 135.793), (33.849, 135.121), (34.597, 135.079), (34.376, 133.34),
        (33.905, 132.157), (33.886, 130.986), (33.15, 132.0), (31.45, 131.333),
        (31.03, 130.686), (31.418, 130.202), (32.319, 130.448), (32.61, 129.815),
        (33.296, 129.408), (33.604, 130.354), (34.233, 130.878), (34.75, 131.884),
        (35.433, 132.618), (35.732, 134.608), (35.527, 135.678), (37.305, 136.724),
        (36.827, 137.391), (37.827, 138.858), (38.216, 139.426), (39.439, 140.055),
        (40.563, 139.883), (41.195, 140.306), (41.379, 141.369), (39.992, 141.914),
        (39.181, 141.885),
    ],
    [
        (43.961, 144.613), (44.385, 145.321), (43.262, 145.543), (42.988, 144.06),
        (41.995, 143.184), (42.679, 141.611), (41.585, 141.067), (41.57, 139.955),
        (42.564, 139.818), (43.333, 140.312), (43.389, 141.381), (44.772, 141.672),
        (45.551, 141.968), (44.51, 143.143), (44.174, 143.91), (43.961, 144.613),
    ],
    [
        (33.464, 132.371), (34.06, 132.924), (33.945, 133.493), (34.365, 133.904),
        (34.149, 134.638), (33.806, 134.766), (33.201, 134.203), (33.522, 133.793),
        (33.29, 133.28), (32.705, 133.015), (32.989, 132.363), (33.464, 132.371),
    ],
]
