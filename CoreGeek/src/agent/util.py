"""几何与弹道工具：切比雪夫距离已在 protocol，这里提供弹道直线与锥形校验。"""
from __future__ import annotations

from .protocol import Pos


def bresenham_line(a: Pos, b: Pos) -> list[Pos]:
    """整数直线格序列（含端点 a..b），用于攻击弹道。"""
    dx = abs(b.x - a.x)
    dy = abs(b.y - a.y)
    sx = 1 if b.x > a.x else -1
    sy = 1 if b.y > a.y else -1
    err = dx - dy
    cells: list[Pos] = []
    x, y = a.x, a.y
    while True:
        cells.append(Pos(x, y))
        if x == b.x and y == b.y:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return cells


def cone_check(origin: Pos, targets: list[Pos], half_angle_deg: float = 45.0) -> bool:
    """所有目标相对 origin 的方向两两夹角 ≤ 2*half_angle（默认 90° 锥）。
    用点积判定向量夹角：dot>=0 即夹角≤90°。"""
    if len(targets) <= 1:
        return True
    vecs = [Pos(p.x - origin.x, p.y - origin.y) for p in targets]
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            dot = vecs[i].x * vecs[j].x + vecs[i].y * vecs[j].y
            if dot < 0:
                return False
    return True


def angle_ok(origin: Pos, a: Pos, b: Pos, half_angle_deg: float = 45.0) -> bool:
    """a、b 相对 origin 夹角 ≤ 2*half_angle。"""
    v1 = Pos(a.x - origin.x, a.y - origin.y)
    v2 = Pos(b.x - origin.x, b.y - origin.y)
    dot = v1.x * v2.x + v1.y * v2.y
    return dot >= 0
