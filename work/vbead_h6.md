# V-0250-VB-12 H6 가상 비드 측정 (release/v0.25.0 C1, 시험 tests/doe/test_vbead_h6.py)

기준: range guard 기본(synth_guard.rules — flip_deg 60·jac_min 0.3·tria 10°·steps 5·min_keep_frac 0.25) + A 전용 warp_max_deg 15°.
D = d_max·0.5 d_max 에서 inverted·새 품질 위반 수(jac·tri·warp), 발자국 밖 이동 최대, range guard 단일([0, d_max]).

| 위치 | 단면 | h | n_fp | inverted (d_max / ½) | jac·tri 새 위반 | warp > 15° 새 요소 (d_max / ½) | warp 최대 ° | 밖 이동 | range guard |
|---|---|---|---|---|---|---|---|---|---|
| 위 부모 바닥 띠 y 654, x 400→600 (ξ, derive ok — VB_WALL_COARSE n_wall 1.67, stretch_max 1.414) | W 15·θ 45·d 5·r 0 | 3.00 | 655 | 0 / 0 | 0 | 23 / 15 | 40.6 | 0 | blocked, usable [0, 0.4687], warp |
| 같은 선, r 5 | W 15·θ 45·d 5·r 5 | 3.00 | – | – | – | – | – | – | limited, usable [0, 1.25], warp |
| 위 띠 30° (p0 700,649 L 20) | W 15·θ 45·d 5 | – | – | – | – | – | – | – | 거부 VB_PLATE_EDGE(띠 폭 ≈ 40 mm) |
| 평탄부 plateau (125,300) ξ L 120 (host 판정만 plateau — 순수 장) | W 15·θ 45·d 5·r 0 | 2.91 | 405 | 0 / 0 | 0 | 152 / 128 | 55.7 | 0 | blocked, usable [0, 0.1562], warp |
| 평탄부 plateau (250,300) 30° L 100 | W 15·θ 45·d 5·r 0 | 2.78 | 373 | 0 / 0 | 0 | 95 / 81 | 62.5 | 0 | blocked, usable [0, 0.1562], warp |

결론: 뒤집힘 0(모든 칸), 발자국 밖 이동 0. range guard 는 warpage 기준(15°)으로 r 0 이면 blocked — work/findings.md VB-C1-5(메인 결정).
H6 부모 바닥은 가장자리 띠뿐 — VB-C1-6.

## 개정 2·3 측정 (r 생략 = min(h, r_cap), A warp = 정보, 평탄부 host, 깊이 보상 — 시험 tests/doe/test_vbead_h6.py, V-0250-VB-23·24)

모두 실제 derive(host 덮어쓰기 없음)·실제 `guard_selection`(뒤집힘·jac·tri·넓이 비 기준 — warp 는 정보). 방향 = 자동(평탄부 = level
부호 → +n0 쪽, 띠 = frame n 반대).

| 위치 | host | 단면 | h | r(기본) | n_fp | stretch_max | inverted (d_max / ½) | jac·tri 새 위반 | warp > 15° (d_max / ½) · 최대 ° | 밖 이동 | range guard |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 위 띠 y 654, x 400→600 (ξ) | base | W 15·θ 45·d 5 | 3.00 | 3.00 | 671 | 1.406 | 0 / 0 | 0 | 23 / 19 · 36.7 | 0 | **ok, usable [0, 5]**, warp n 23 |
| 위 띠 30° (700, 649) L 20 | base | 같음 | – | – | – | – | – | – | – | – | 거부 VB_PLATE_EDGE + VB_OVER_BEAD(발자국 +1.25·r·tan22.5° ≈ 1.55 mm) |
| 평탄부 (150, 180) ξ L 120 | plateau(floor 11) | W 15·θ 45·d 5 | 2.98 | 2.98 | 457 | 1.415 | 0 / 0 | 0 | 78 / 54 · 49.7 | 0 | **ok, usable [0, 5]**, warp n 78 |
| 평탄부 (250, 180) 30° L 60 | plateau | W 15·θ 45·d 5 | 2.91 | 2.91 | 286 | 1.416 | 0 / 0 | 0 | 106 / 74 · 43.1 | 0 | **ok, usable [0, 5]**, warp n 106 |
| 평탄부 (200, 480) 30° L 60 | plateau | W 15·θ 60·d 5 | 2.84 | 2.84 | 245 | 1.687 | 0 / 0 | 0 | 95 / 60 · 51.5 | 0 | **ok, usable [0, 5]**, warp n 95 |
| 평탄부 계약 자리 (125, 300) ξ L 120 · (250, 300) 30° L 100 | plateau | W 15·θ 45·d 5 | – | – | – | – | – | – | – | – | 거부(보스·구멍·자식 비드 — VB_OVER_BEAD·ISLAND·HOLE) |

결론: 뒤집힘 0·jac·tri 새 위반 0·발자국 밖 이동 0, range guard 모두 ok(usable = d_max). warp 정보는 남음(n 23~106, 최대 37~51°).
평탄부 30° 는 L 100 이 들어갈 빈자리가 없어 L 60(VB-C1-17). (250, 180) θ 60 은 그 자리 h 2.97 > run 2.89 라 VB_MESH_COARSE → (200, 480).
