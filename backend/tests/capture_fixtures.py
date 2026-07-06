"""Synthetic camera fixtures for Tier-3 capture tests — generated programmatically (numpy/OpenCV).

No real customer imagery (TESTING-STRATEGY §8: synthetic only). Each helper produces a BGR
``np.ndarray`` (or a list of frames) with a KNOWN ground-truth property so the discrimination tests
can assert real separation, not assertion-of-existence.
"""

from __future__ import annotations

import cv2
import numpy as np


def _intrinsics(n: int) -> np.ndarray:
    f = 1.2 * float(n)
    return np.array([[f, 0, n / 2], [0, f, n / 2], [0, 0, 1]], dtype=np.float64)


def tilt_homography(n: int, axis: str, deg: float) -> np.ndarray:
    """Homography of a fronto-parallel plane rotated ``deg`` about ``axis`` ('x' or 'y')."""
    k = _intrinsics(n)
    t = np.deg2rad(deg)
    if axis == "x":
        rot = np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]])
    else:
        rot = np.array([[np.cos(t), 0, np.sin(t)], [0, 1, 0], [-np.sin(t), 0, np.cos(t)]])
    return k @ rot @ np.linalg.inv(k)


def page_on_background(n: int = 400, blur: bool = False, glare: bool = False) -> np.ndarray:
    """A bright, textured document quad on a dark background.

    ``blur`` -> defocused (low Laplacian variance); ``glare`` -> adds a concentrated specular
    hotspot. The page quad is convex and covers >20% of the frame so it is detectable.
    """
    img = np.full((n, n, 3), 35, np.uint8)  # dark contrasting background
    margin = n // 6
    quad = np.array(
        [[margin, margin], [n - margin, margin + 8],
         [n - margin - 8, n - margin], [margin + 6, n - margin - 4]], np.int32
    )
    cv2.fillConvexPoly(img, quad, (235, 235, 235))
    # high-frequency text-like content gives the focus measure something to resolve
    rng = np.random.default_rng(0)
    for _ in range(120):
        x = int(rng.integers(margin + 10, n - margin - 10))
        y = int(rng.integers(margin + 10, n - margin - 10))
        cv2.circle(img, (x, y), 2, (25, 25, 25), -1)
    for y in range(margin + 20, n - margin - 10, 14):
        cv2.line(img, (margin + 12, y), (n - margin - 12, y), (40, 40, 40), 1)
    if blur:
        img = cv2.GaussianBlur(img, (21, 21), 0)
    if glare:
        cx, cy = n // 2, n // 3
        cv2.circle(img, (cx, cy), n // 12, (255, 255, 255), -1)
        img = cv2.GaussianBlur(img, (7, 7), 0)
    return img


def diffuse_page(n: int = 200) -> np.ndarray:
    """A well-exposed matte page: bright but NOT clipped, no specular hotspot."""
    rng = np.random.default_rng(1)
    img = np.full((n, n, 3), 205, np.uint8)
    noise = rng.integers(-15, 15, (n, n, 3)).astype(np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def screen_glare_page(n: int = 200) -> np.ndarray:
    """A mid-tone field with a concentrated, blown-out specular reflection (glossy screen)."""
    rng = np.random.default_rng(2)
    img = np.full((n, n, 3), 120, np.uint8)
    img = np.clip(img.astype(np.int16) + rng.integers(-10, 10, (n, n, 3)), 0, 255).astype(np.uint8)
    cv2.circle(img, (n // 2, int(n * 0.4)), n // 9, (255, 255, 255), -1)
    cv2.circle(img, (int(n * 0.3), int(n * 0.7)), n // 20, (255, 255, 255), -1)
    return img


def diffuse_gray(n: int = 256) -> np.ndarray:
    """A smooth-gradient diffuse page (grayscale): broadband spectrum, no periodic carrier."""
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:n, 0:n]
    base = 120 + 0.08 * xx + 0.08 * yy
    base = base + rng.normal(0, 3, (n, n))
    return np.clip(base, 0, 255).astype(np.uint8)


def screen_grid_gray(n: int = 256, period: int = 4) -> np.ndarray:
    """A high-frequency periodic sinusoid (re-imaged LCD subpixel/moire carrier)."""
    rng = np.random.default_rng(4)
    _yy, xx = np.mgrid[0:n, 0:n]
    grid = 127 + 100 * np.sin(2 * np.pi * xx / period)
    grid = grid + rng.normal(0, 3, (n, n))
    return np.clip(grid, 0, 255).astype(np.uint8)


def _gray_to_bgr(gray: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(gray.astype(np.uint8), cv2.COLOR_GRAY2BGR)


def static_frames(n: int = 64, count: int = 12) -> list[np.ndarray]:
    """Identical frames — a static photo of a document (zero temporal variance)."""
    rng = np.random.default_rng(5)
    base = rng.integers(0, 255, (n, n)).astype(np.uint8)
    return [_gray_to_bgr(base.copy()) for _ in range(count)]


def live_frames(n: int = 64, count: int = 12) -> list[np.ndarray]:
    """Aperiodic per-pixel micro-motion — live capture (high variance, low loop autocorr)."""
    rng = np.random.default_rng(6)
    base = rng.integers(0, 255, (n, n)).astype(np.float64)
    out = []
    for _ in range(count):
        f = np.clip(base + rng.normal(0, 7, (n, n)), 0, 255).astype(np.uint8)
        out.append(_gray_to_bgr(f))
    return out


def looped_frames(n: int = 64, count: int = 12, loop: int = 3) -> list[np.ndarray]:
    """A short clip repeated — replayed video loop (variance present, strong loop autocorr)."""
    rng = np.random.default_rng(7)
    base = rng.integers(0, 255, (n, n)).astype(np.float64)
    clip = [np.clip(base + rng.normal(0, 7, (n, n)), 0, 255).astype(np.uint8) for _ in range(loop)]
    return [_gray_to_bgr(clip[i % loop].copy()) for i in range(count)]


def _textured_document(n: int, margin_frac: float = 0.25) -> np.ndarray:
    """A trackable textured document filling the centre of an n x n grayscale frame.

    ``margin_frac`` controls how much of the frame the document occupies (default 25% margin ->
    document covers 50% of each dimension, 25% of area); a larger fraction shrinks the document,
    e.g. for the small-document-in-a-big-frame regression fixture.
    """
    img = np.full((n, n), 30, np.uint8)
    margin = int(n * margin_frac)
    cv2.rectangle(img, (margin, margin), (n - margin, n - margin), 220, -1)
    rng = np.random.default_rng(99)
    for _ in range(80):
        x = int(rng.integers(margin + 5, n - margin - 5))
        y = int(rng.integers(margin + 5, n - margin - 5))
        cv2.circle(img, (x, y), 2, int(rng.integers(0, 120)), -1)
    return img


def challenge_sequence(axis: str, max_deg: float, n: int = 300, steps: int = 8) -> list[np.ndarray]:
    """A frame sequence of a flat document tilting smoothly from 0 to ``max_deg`` about ``axis``."""
    doc = _textured_document(n)
    frames = []
    for i in range(steps):
        deg = max_deg * i / (steps - 1)
        homog = tilt_homography(n, axis, deg)
        warped = cv2.warpPerspective(doc, homog, (n, n), borderValue=30)
        frames.append(cv2.cvtColor(warped, cv2.COLOR_GRAY2BGR))
    return frames


def static_challenge_sequence(n: int = 300, steps: int = 8) -> list[np.ndarray]:
    """A document that does not move (replay of a frozen photo) — no commanded motion realised."""
    doc = _textured_document(n)
    frame = cv2.cvtColor(doc, cv2.COLOR_GRAY2BGR)
    return [frame.copy() for _ in range(steps)]


def small_document_over_busy_static_background(
    axis: str, max_deg: float, n: int = 300, steps: int = 8, margin_frac: float = 0.38
) -> list[np.ndarray]:
    """The document tilts correctly, but sits inside a cluttered, perfectly STATIC background
    (many more corner candidates than the document itself) — approximates a small ID card held up
    in front of a real, busy, mostly-still room (a panelled door, a hinge, a face). Regression
    fixture for the corner-seeding fix in ``capture/challenge.py::track_corners``: unmasked
    ``goodFeaturesToTrack`` would seed mostly on the static background, corrupting the single-
    homography fit with a mix of two different motions even though the document itself moved
    exactly as commanded.

    The document is warped by the SAME per-sequence homography (``tilt_homography(n, ...)``, full
    frame size) used by ``challenge_sequence`` — critically at the SAME ``n``, so the recovered
    angle decomposition (which assumes intrinsics derived from the actual frame size) stays valid.
    Only the warped document's own (non-background-fill) pixels are composited onto the static
    clutter each frame, so the clutter never moves while the small document tilts realistically.
    """
    doc = _textured_document(n, margin_frac=margin_frac)
    margin = int(n * margin_frac)

    rng = np.random.default_rng(11)
    background = np.full((n, n), 70, np.uint8)
    pad = 20  # keep a clean buffer (> max shape radius) around the document's own border so
    # background clutter never fuses into its contour (Canny + dilation would otherwise merge an
    # adjacent shape into a non-convex blob, defeating quad detection entirely rather than testing
    # the fix). Circles only (bounded radius) — a line's far endpoint is harder to keep clear.
    for _ in range(80):
        x, y = int(rng.integers(0, n)), int(rng.integers(0, n))
        if margin - pad <= x <= n - margin + pad and margin - pad <= y <= n - margin + pad:
            continue
        cv2.circle(background, (x, y), int(rng.integers(3, 8)), int(rng.integers(0, 255)), -1)

    frames = []
    for i in range(steps):
        deg = max_deg * i / (steps - 1)
        homog = tilt_homography(n, axis, deg)
        warped_doc = cv2.warpPerspective(doc, homog, (n, n), borderValue=30)
        frame = background.copy()
        doc_pixels = np.abs(warped_doc.astype(np.int16) - 30) > 3  # anything but the border fill
        frame[doc_pixels] = warped_doc[doc_pixels]
        frames.append(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
    return frames


def double_perspective_sequence(n: int = 300, steps: int = 8) -> list[np.ndarray]:
    """Photo-of-screen analogue: the left half tilts about x, the right half about y, so no single
    planar homography explains the whole 'document' (bezel / double perspective)."""
    doc = _textured_document(n)
    frames = []
    for i in range(steps):
        deg = 14.0 * i / (steps - 1)
        hx = tilt_homography(n, "x", deg)
        hy = tilt_homography(n, "y", deg)
        wx = cv2.warpPerspective(doc, hx, (n, n), borderValue=30)
        wy = cv2.warpPerspective(doc, hy, (n, n), borderValue=30)
        mixed = wx.copy()
        mixed[:, n // 2:] = wy[:, n // 2:]
        frames.append(cv2.cvtColor(mixed, cv2.COLOR_GRAY2BGR))
    return frames
