import math


def radial_positions(
    hub_x: float, hub_y: float, count: int, radius: float = 60.0
) -> list[tuple[float, float]]:
    if count == 0:
        return []
    positions = []
    for i in range(count):
        angle = (2 * math.pi * i) / count
        x = hub_x + radius * math.cos(angle)
        y = hub_y + radius * math.sin(angle)
        positions.append((x, y))
    return positions
