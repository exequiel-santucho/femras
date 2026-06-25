"""Conforming T3 mesh of an arbitrary plane polygon (Delaunay + clip).

Ported from presa_ras.py (build_conforming_t3_mesh and helpers). Boundary edge
utilities support the hydraulic load (free edges on a given face).
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import Delaunay


def point_in_polygon(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xint = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-30) + x1
            if x < xint:
                inside = not inside
    return inside


def _points_on_segment(p1, p2, h):
    p1 = np.asarray(p1, float)
    p2 = np.asarray(p2, float)
    L = np.linalg.norm(p2 - p1)
    n = max(int(np.ceil(L / h)), 1)
    return [(1.0 - i / n) * p1 + (i / n) * p2 for i in range(n + 1)]


def _unique_points(points, tol=1e-7):
    seen, out = set(), []
    for p in points:
        key = (round(p[0] / tol), round(p[1] / tol))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return np.array(out, dtype=float)


def conforming_t3_mesh(poly, h, max_edge_factor=2.75):
    """Return (nodes, elements) for a polygon, mean element size ~ h."""
    poly = np.asarray(poly, float)
    xmin, ymin = poly.min(axis=0)
    xmax, ymax = poly.max(axis=0)

    pts = []
    for i in range(len(poly)):
        pts.extend(_points_on_segment(poly[i], poly[(i + 1) % len(poly)], h))
    for x in np.arange(xmin + h, xmax, h):
        for y in np.arange(ymin + h, ymax, h):
            if point_in_polygon(x, y, poly):
                pts.append(np.array([x, y], float))
    pts = _unique_points(pts)

    tri = Delaunay(pts)
    elements = []
    for simplex in tri.simplices:
        coords = pts[simplex]
        c = coords.mean(axis=0)
        if not point_in_polygon(c[0], c[1], poly):
            continue
        max_edge = max(np.linalg.norm(coords[a] - coords[b])
                       for a, b in [(0, 1), (1, 2), (2, 0)])
        if max_edge > max_edge_factor * h:
            continue
        A2 = ((coords[1, 0] - coords[0, 0]) * (coords[2, 1] - coords[0, 1])
              - (coords[2, 0] - coords[0, 0]) * (coords[1, 1] - coords[0, 1]))
        if abs(A2) < 1e-12:
            continue
        if A2 < 0.0:
            simplex = [simplex[0], simplex[2], simplex[1]]
        elements.append(simplex)
    elements = np.array(elements, dtype=int)

    used = np.unique(elements.ravel())
    remap = -np.ones(len(pts), dtype=int)
    remap[used] = np.arange(len(used))
    nodes = pts[used].copy()
    elements = remap[elements]
    return nodes, elements


def nearest_node(nodes, point):
    return int(np.argmin(np.sum((nodes - np.asarray(point)) ** 2, axis=1)))


def boundary_edges(elements):
    """Map edge (i,j) -> owner elements. Free edges have a single owner."""
    edges = {}
    for e, conn in enumerate(elements):
        for a, b in [(0, 1), (1, 2), (2, 0)]:
            key = tuple(sorted((int(conn[a]), int(conn[b]))))
            edges.setdefault(key, []).append(e)
    return edges


def vertical_face_edges(nodes, elements, x_face=0.0, tol=1e-7):
    """Free boundary edges lying on the vertical line x = x_face (e.g. upstream)."""
    edges = []
    for (i, j), owners in boundary_edges(elements).items():
        if len(owners) == 1:
            if abs(nodes[i, 0] - x_face) < tol and abs(nodes[j, 0] - x_face) < tol:
                edges.append((i, j))
    return sorted(edges, key=lambda ij: min(nodes[ij[0], 1], nodes[ij[1], 1]))


def face_boundary_edges(nodes, elements, p1, p2, tol=None):
    """Free boundary edges whose both nodes lie on the segment [p1, p2].

    Generalises ``vertical_face_edges`` to an arbitrary polygon edge.
    ``tol`` defaults to 1e-4 * |p2-p1| (relative), floored at 1e-7.
    Returns edges sorted by the y-coordinate of their lower node.
    """
    p1 = np.asarray(p1, float)
    p2 = np.asarray(p2, float)
    seg_len = float(np.linalg.norm(p2 - p1))
    if seg_len < 1e-15:
        return []
    if tol is None:
        tol = max(1e-4 * seg_len, 1e-7)
    u = (p2 - p1) / seg_len  # unit vector along segment

    def on_seg(n_idx):
        v = nodes[n_idx] - p1
        t = float(np.dot(v, u))
        if t < -tol or t > seg_len + tol:
            return False
        return float(np.linalg.norm(v - t * u)) < tol

    edges = []
    for (i, j), owners in boundary_edges(elements).items():
        if len(owners) == 1 and on_seg(i) and on_seg(j):
            edges.append((i, j))
    return sorted(edges, key=lambda ij: min(nodes[ij[0], 1], nodes[ij[1], 1]))


def nodes_on_segment(nodes, elements, p1, p2, tol=None):
    """Unique mesh-node indices lying on the boundary segment [p1, p2].

    Built on :func:`face_boundary_edges`, so it shares the same relative
    tolerance and only returns nodes on *free* boundary edges of the segment.
    Used to apply an :class:`~femras.config.EdgeSupportCfg` to a whole edge.
    """
    edges = face_boundary_edges(nodes, elements, p1, p2, tol)
    if not edges:
        return np.array([], dtype=int)
    return np.unique(np.array(edges, dtype=int).ravel())


def base_nodes(nodes, y_base=0.0, tol=1e-7):
    return np.where(np.abs(nodes[:, 1] - y_base) < tol)[0]
