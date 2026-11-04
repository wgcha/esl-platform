# 참고: Radioss Ch/R 3 mm 낙하 메시 기준 (HyperMesh BatchMesher param·criteria 원문)

- 출처: GitHub 이슈 #53 "mesh criteria , parameter" (wgcha, 2026-11-03) — 본문 = criteria 파일, 첫 코멘트 = param 파일.
- 용도: 강성 평가 스터디 ④ 형상 직접 비교의 메싱 설정(`bead_doe.compare.mesh`·`defeature`·`quality`) 근사 기준
  (계약 `docs/contracts/esl_step_compare.md` SC-D-5·SC-D-13). 값 대응·한계는 계약 문서 참조.
- 아래 두 절은 원문 그대로(수정 금지).

## 1. criteria 파일 (이슈 #53 본문)

```text
This Criteria file was created with Criteria Editor application

#    Criterion        On    Wt  Ideal     Good     Warn    Fail  Worst  Solver   Color Priority

 0 penalty value                 0.00     0.00     0.80    1.00  10.00
 1 min length           1  1.0   3.00     2.40     1.80    1.20   0.90       10      59       0
 2 max length           1  1.0   3.00     3.75     4.50    5.25   6.00        0      39       1
 3 aspect ratio         1  1.0   1.00     2.00     4.40    5.00  10.00        3      41       2
 4 warpage              1  1.0   0.00     5.00    13.00   15.00  30.00        3      56       3
 5 max angle quad       1  1.0  90.00   110.00   134.00  140.00 160.00        0      28       4
 6 min angle quad       1  1.0  90.00    70.00    46.00   40.00  20.00        0      61       5
 7 max angle tria       1  1.0  60.00    80.00   112.00  120.00 150.00        0      19       6
 8 min angle tria       1  1.0  60.00    50.00    34.00   30.00  15.00        0      22       7
 9 skew                 1  1.0   0.00    10.00    34.00   40.00  70.00        3      46       8
10 jacobian             1  1.0   1.00     0.90     0.70    0.60   0.30        0      57       9
11 chordal dev          0  1.0   0.00     0.30     0.80    1.00   2.00        0      29      10
12 % of trias           1  1.0   0.00     6.00    10.00   15.00  20.00        0       0      -1
13 taper                1  1.0   0.00     0.20     0.50    0.60   0.90        3      53      11
14 time_step            1  1.0  1.E-05   1.E-05   5.E-07  1.E-07                      5      12
15 QI color legend                  32       32        7       6      3       3      -1
 Global_solver 3

This Criteria file was created with Criteria3D Editor application

#  Criterion                On     Wt    Ideal     Good    Warn   Fail   Worst  Solver   Color Priority

 0 {Penalty value}                        0.00     0.01    0.80   1.00   10.00
 1 {Min Size}                 1  2.00     3.00    2.370   0.900  0.600   0.360       10      59       0
 2 {Max Size}                 1  1.00     3.00     4.50    7.50   9.00   15.00        0      39       1
 3 {Tet Collapse}             1  1.00     1.00     0.94    0.78   0.50    0.44        0      57       2
 4 {Vol Skew}                 1  1.00     0.00     0.10    0.57   0.90    0.95        0      41       3
 5 {Aspect Ratio}             1  1.00     1.00     3.00    5.00   8.00   12.00        0      53       4
 6 {Skew}                     1  1.00     0.00    10.00   55.00  60.00   90.00        0      46       5
 7 {Vol AR}                   1  1.00     1.00     3.00    5.00   8.00   12.00        0      28       6
 8 {Warpage}                  1  2.00     0.00     5.00   15.00  20.00   90.00        0      56       7
 9 {Max Face Angle Quad}      1  1.00    90.00   120.00  140.00 146.00  180.00        0      21       8
10 {Min Face Angle Quad}      1  1.00    90.00    60.00   40.00  17.00    0.00        0      25       9
11 {Max Face Angle Tria}      1  1.00    60.00    80.00  140.00 146.00  180.00        0      22      10
12 {Min Face Angle Tria}      1  1.00    60.00    50.00   20.00  17.00    0.00        0      19      11
13 {Jacobian}                 1  1.00     1.00     0.90    0.70   0.50    0.00        0      19      12
14 {Cell Squish}              1  1.00     0.00     0.11    0.63   0.95    1.06        0      22      13
15 {Equia Skew}               1  1.00     0.00    10.00   55.00  60.00   90.00        0      29      14
16 {Orthogonality}            0  1.00     1.00     0.50    0.25   0.20    0.05        0      21      15
17 {Size Ratio}               0  1.00     0.77     0.50    0.25   0.10    0.05        0       4      16
18 {Time Step}                1          1.E-05   1.E-05  5.E-07 1.E-07               0       5      17

This Criteria file was created with Criteria1D Editor application

#  Criterion                On           Ideal                    Fail          Solver   Color Priority

 1 {Min Size 1D}              1              10                       2               0      59       0
 2 {Max Size 1D}              1              10                      30               0      39       1
 3 {Time Step 1D}             0               1                    0.25               0       5       2
```

## 2. param 파일 (이슈 #53 코멘트)

```text
#This Param file was created with Criteria/Param Editor application

fileversion 20210

#flags:

geometry_cleanup_flag                1
meshing_flag                         5

#mesh:

element_size                         3
element_type                         2
mesh_align                           3
element_order                        1
surf_component                       1
feature_angle                        10

# Holes Design Table:

holes_table_begin

# General switches:

appl_surf(0)
appl_solid(0)
appl_cordsfiles(0)
appl_flanged_suppr(1)
flanged_suppr_height(1.5)
narrow_slots_type(2)
slots_squaretip_maxwidth(  L*1.4 )
slots_squaretip_maxchorddev(  -1 )
appl_rmv_washer_loops(1)
abs_fixed_nodes_count_max(0)
solid_tube_diams_ratio_max(2.5)
solid_tube_cross_sect_size_max(100)

# holes design records:

shape(1) rad(0.0,4) do action(1) washer(0) mesh_ptrn(0)
shape(1) rad(4,30) do action(0) elems(6) washer(1) layers(auto) mesh_ptrn(0)

shape(2) width(0.0,1.9) length(0.0,14) do action(1) washer(0) mesh_ptrn(0)
shape(2) width(0.0,1.9) length(14,-1) do action(0) elems(auto) washer(0) mesh_ptrn(3)
shape(2) width(1.9,8) length(1.9,-1) do action(0) elems(auto) washer(0) mesh_ptrn(2)
shape(2) width(8,14) length(8,-1) do action(0) elems(6) washer(0) mesh_ptrn(2)
shape(2) width(14,60) length(14,-1) do action(0) elems(6) washer(1) layers(auto) mesh_ptrn(0)

shape(62) eq_diam(0.0,8) do action(1) washer(0) mesh_ptrn(0)

rad(0.0,4) solid(1) do action(1)
rad(4,6) solid(1) do action(0) elems(4)
rad(6,30) solid(1) do action(0) elems(6)

holes_table_end

#edge fillets:

edge_fillet_recognition              0
max_fillet_radius                    9

#surface fillets:

surface_fillet_table_begin

surface_fillet_recognition(0)
minimize_transitions(1)

surface_fillet_table_end

#delete duplicates:

del_dupl_surfs_flag                  1
del_dupl_surfs_tol                   0.2

#edges stitch:

edges_stitch_flags                   3
max_edges_stitch_tol                 0.2

#fix overlapping surfs:

fix_overlapsurfs_flag                1
overlapsurfs_maxtangangle            -1.0

#narrow surfaces:

merge_narrow_surfs                   1
narrow_surfs_merge_width             Lmin*0.5
narrow_surfs_sharp_edge_merge_width  Lmin*0.5

#beads:

beads_suppression                    1
beads_recognition                    0
minimal_beads_height                 2

#capture beads axis
beads_treat_flags                    64

#flanges:

flange_recognition                   0
flange_elements_across               2
flange_max_width                     35
flange_min_width                     5
flanges_treat_flags                  1
flange_max_remove_width              -1.0

#tria_reduction:

appl_tria_reduction                  1
common_mesh_flow                     1

#thin solids:

extract_thinsolids                   0
midsurf_method                       3
thinsolid_ratio                      0.3
max_thickness                        15
extract_feature_angle                25
pre_midsurf_cleanup                  0
direct_midmesh                       0
ignore_flat_edges                    1
flatten_connections                  1
step_offset_mode                     0
defeat_open_width_factor_on          1
defeat_open_width_factor             0.5
supp_proxim_edges_on                 1
supp_proxim_edges                    0.9
combine_nonmanifold_on               1
combine_nonmanifold                  0.4
fillet_treatment_on                  1
fillet_treatment_factor              0.6
defeature_ribs_width_on              1
defeature_ribs_width                 0.9
midmesh_extract_elem_size            3

#logo:

remove_logo                          0
logo_max_size                        22
logo_max_height                      4
logo_min_concavity                   0.2

#threads:

threads_removal                      0
threads_toremove_max_depth           0.2
threads_replacediametertype          -2

#element cleanup:

folded_elems_angle                   100
smooth_elems_target                  0.2
fillets_mesh_flow                    0

#smoothing across edges options:

failed_elems_cleanup_flgs            8
move_nodes_across_feature_edges      1
featureedge_nodes_moveacross_max     L*0.1
move_nodes_across_free_edges         1
freeedge_nodes_moveacross_max        L*0.05
move_nodes_across_t_edges            0
tedge_nodes_moveacross_max           L*0.025

#correct warped elements:

move_normal_flag                     0
move_normal_dist                     10
divide_warped_quads                  1
aggressive_elems_quality_correction  0

ignore_comps_boundary                0
gen_topology_prepare_flags           7

use_wildcards_for_compsnames         0

cleanup_tolerances                   auto

suppress_features_rate               0
feat_charsize_method                 0
custom_feat_suppr_maxangle           25
uncond_constr_lines_suppress         0
aggressive_fillet_lines_suppress     0

ext_mesh_api_id                         0
```
