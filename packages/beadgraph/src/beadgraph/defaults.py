"""Package defaults = esl ``DEFAULTS["select"]["graph"]`` (contract §5.5) minus the esl-only ``enabled`` switch.
esl always passes its full merged cfg (R-BG-7); V-BG-14 checks that both copies agree."""

DEFAULTS = {
    "feature_angle_deg": 10.0,                       # BG-D-2 (#53 param feature_angle)
    "level_tol_mm": 0.3,
    "min_floor_area_mm2": 12.0,
    "root_free_frac": 0.2,
    "raster_mm": 1.0,
    "island": {"max_mm": 60.0, "straddle_frac": 0.15},           # D8
    "bead": {"max_width_mm": 80.0, "prune_k": 2.2, "bend_deg": 50.0, "width_jump": 0.35, "min_zone_mm": 12.0,
             "open_ext_mm": 90.0, "absorb_len_mm": 60.0},       # absorb_len_mm = D7 short-strip absorption
    "morph": {"ramp_k": 3.0, "outside_tol_mm": 1.0e-6, "achieved_tol_mm": 1.0e-6,
              "corner": {"area_ratio_min": 0.35, "shrink": 0.8, "iters": 40},
              "w_smooth_iters": 3},                 # W outward-direction relaxation (continuous at kinks / joins)
    "sym_tol_mm": 0.5,                               # BG-D-17·21
    "limits": {"max_elems": 250000, "timeout_s": 180, "max_raster_px": 4000000},
}

# keys the morph needs that live in other esl sections (select.hold — SR-D-9, select.blend — BS R_auto,
# select.range — default ranges); esl passes its own values under these names, these are the same defaults.
MORPH_EXTRA = {
    "hold": {"ring_mm": 3.0, "blend_mm": 8.0},
    "blend": {"min_mm": 15.0, "k": 8.0},
    "quality": {"flip_deg": 60.0},
}
