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
