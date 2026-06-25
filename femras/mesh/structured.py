"""Structured Q4 mesh for a rectangular region with an optional rectangular
notch (RILEM-type notched beam). Ported from viga_rilem.py.
"""

from __future__ import annotations

import numpy as np


def notched_beam_mesh(L, H, nx, ny, notch_width=0.0, notch_height=0.0):
    """Return (nodes, elements, n_removed) for a beam of size L x H.

    A centred rectangular notch of ``notch_width`` x ``notch_height`` is carved
    from the bottom edge by removing the overlapping elements.
    """
    nodes = []
    for j in range(ny + 1):
        y = H * j / ny
        for i in range(nx + 1):
            nodes.append([L * i / nx, y])
    nodes = np.array(nodes, dtype=float)

    x_min = L / 2.0 - notch_width / 2.0
    x_max = L / 2.0 + notch_width / 2.0
    y_max = notch_height

    elems = []
    removed = 0
    for j in range(ny):
        for i in range(nx):
            n1 = j * (nx + 1) + i
            n2 = n1 + 1
            n4 = n1 + (nx + 1)
            n3 = n4 + 1
            elem = [n1, n2, n3, n4]
            coords = nodes[elem, :]
            overlap_x = (coords[:, 0].max() > x_min) and (coords[:, 0].min() < x_max)
            overlap_y = (coords[:, 1].max() > 0.0) and (coords[:, 1].min() < y_max)
            if notch_width > 0.0 and notch_height > 0.0 and overlap_x and overlap_y:
                removed += 1
            else:
                elems.append(elem)
    elems = np.array(elems, dtype=int)

    used = np.unique(elems.flatten())
    remap = {old: new for new, old in enumerate(used)}
    nodes_new = nodes[used, :]
    elems_new = np.array([[remap[n] for n in e] for e in elems], dtype=int)
    return nodes_new, elems_new, removed


def nearest_node(nodes, x, y):
    d = (nodes[:, 0] - x) ** 2 + (nodes[:, 1] - y) ** 2
    return int(np.argmin(d))


def top_load_patch_nodes(nodes, x_center, y_top, mode="three_nodes_centered"):
    """Nodes on the top edge near ``x_center`` for an imposed displacement."""
    top = np.where(np.isclose(nodes[:, 1], y_top))[0]
    top = top[np.argsort(nodes[top, 0])]
    x_top = nodes[top, 0]
    c = int(np.argmin(np.abs(x_top - x_center)))
    if mode == "one_node":
        return [int(top[c])]
    if mode == "three_nodes_centered":
        i0 = max(c - 1, 0)
        i2 = min(c + 1, len(top) - 1)
        return list(dict.fromkeys([int(top[i0]), int(top[c]), int(top[i2])]))
    raise ValueError("unknown load patch mode")
