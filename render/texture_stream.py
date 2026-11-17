"""Texture streaming policy helpers.

The streaming loop is driven by a few pure functions so that the policy can be
tested without a GPU or a renderer:

* :func:`required_mip` turns a screen-projected size into the coarsest mip that
  is still detailed enough (large projected size -> low mip level).
* :func:`merge_io_requests` batches per-mip requests into contiguous ranges per
  texture, ordered by urgency (projection error / visibility priority).
* :func:`total_budget` accounts for texture bytes plus the upload and staging
  overhead that the old budget ignored.
* :func:`select_evictions` picks LRU candidates that are **not** referenced by
  a live material.
* :func:`fallback_mip` returns the best resident lower mip when a load fails,
  so a material degrades instead of turning purple.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


def required_mip(full_size: int, target_size: int) -> int:
    """Return the mip level needed to bring ``full_size`` down to ``target_size``.

    ``target_size`` is the on-screen size derived from the projected error.
    Each mip halves the resolution, so this is the number of halvings needed
    before the texture is no longer larger than the target.  A target at or
    above the source size needs no streaming (level 0).
    """
    full = int(full_size)
    target = int(target_size)

    if full <= 1:
        return 0
    if target <= 0:
        # A degenerate target still selects the smallest mip (1x1).
        target = 1

    level = 0
    size = full
    while size > target and size > 1:
        size //= 2
        level += 1
    return level


def merge_io_requests(
    requests: Iterable[Mapping[str, Any]],
    current_generation: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Merge per-mip IO requests into contiguous ranges per texture.

    Requests are grouped by texture and collapsed into ``(first, last)`` mip
    ranges, so loading mips 0 and 1 of the same texture costs one read instead
    of two.  Groups are ordered by visibility first, then by descending
    priority (the highest-priority mip of the group, i.e. the request with the
    largest projected error); ties keep first-seen order for deterministic
    output.  Requests may carry ``'visible': False`` (an off-screen or
    frustum-culled texture) to be streamed only after everything visible,
    however large its projected error is.

    ``requests`` items use the shape ``{'texture', 'mip', 'priority'?}``.
    When ``current_generation`` is provided, requests tagged with a different
    ``generation`` are dropped.  The streamer bumps the generation on a camera
    teleport, which cancels high-resolution requests for the old location
    before they occupy budget.
    """
    groups: Dict[Any, Dict[str, Any]] = {}
    next_order = 0

    for request in requests:
        texture = request.get("texture")
        if texture is None:
            continue

        generation = request.get("generation")
        if (
            current_generation is not None
            and generation is not None
            and generation != current_generation
        ):
            continue

        mip = int(request.get("mip", 0))
        priority = int(request.get("priority", 0))
        visible = bool(request.get("visible", True))

        group = groups.get(texture)
        if group is None:
            group = {
                "mips": set(),
                "priority": priority,
                "visible": visible,
                "order": next_order,
            }
            groups[texture] = group
            next_order += 1

        group["mips"].add(mip)
        # The group inherits the urgency of its most urgent mip.
        group["priority"] = max(group["priority"], priority)
        group["visible"] = group["visible"] or visible

    ordered = sorted(
        groups.items(),
        key=lambda item: (
            not item[1]["visible"],
            -item[1]["priority"],
            item[1]["order"],
        ),
    )

    merged: List[Dict[str, Any]] = []
    for texture, group in ordered:
        mips = sorted(group["mips"])
        if not mips:
            continue

        range_start = range_end = mips[0]
        for mip in mips[1:]:
            if mip == range_end + 1:
                range_end = mip
                continue
            merged.append(
                {
                    "texture": texture,
                    "mips": (range_start, range_end),
                    "priority": group["priority"],
                }
            )
            range_start = range_end = mip
        merged.append(
            {
                "texture": texture,
                "mips": (range_start, range_end),
                "priority": group["priority"],
            }
        )

    return merged


def select_evictions(
    candidates: Sequence[Any],
    refcounts: Mapping[Any, int],
    budget: int,
    sizes: Mapping[Any, int],
) -> List[Any]:
    """Choose textures to evict until the budget is met.

    ``candidates`` is ordered least-recently-used first.  A texture with a
    non-zero reference count is pinned by a live material and is never
    evicted -- skipping it avoids the black patches caused by evicting a
    texture that is still being sampled.

    If only pinned textures remain, eviction stops and returns what could be
    reclaimed; the caller should then lower mip levels instead of thrashing.
    """
    budget = int(budget)
    seen = set()
    total = 0
    for texture in candidates:
        if texture in seen:
            continue
        seen.add(texture)
        total += int(sizes.get(texture, 0))

    evicted: List[Any] = []
    evicted_set = set()
    for texture in candidates:
        if total <= budget:
            break
        if texture in evicted_set:
            continue
        if int(refcounts.get(texture, 0)) > 0:
            continue
        evicted.append(texture)
        evicted_set.add(texture)
        total -= int(sizes.get(texture, 0))

    return evicted


def total_budget(texture_bytes: int, upload_bytes: int, staging_bytes: int) -> int:
    """Return the real memory budget usage for a texture batch.

    Texture bytes alone are not enough: the upload buffer holding the source
    mips and the staging copy used by the transfer queue consume memory too,
    and leaving them out makes the streamer overshoot VRAM.
    """
    return int(texture_bytes) + int(upload_bytes) + int(staging_bytes)


def fallback_mip(requested: int, available: Iterable[int]) -> int:
    """Return the highest resident mip at or below ``requested``.

    Used when an IO request fails: sampling a lower resident mip keeps the
    material shaded with a blurrier texture instead of the default purple
    "missing texture" colour.  If no lower mip is resident, level 0 is
    returned so the caller has a defined base level to bind.
    """
    requested = int(requested)
    resident = sorted({int(mip) for mip in available})

    best = 0
    for mip in resident:
        if mip > requested:
            break
        best = mip
    return best
