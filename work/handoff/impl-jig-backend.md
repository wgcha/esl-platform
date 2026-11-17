# impl-jig-backend 인수 메모
- 완료(커밋 2개): 파서 elem_segs·load_nodes_box, jig_surf, 계획 열, METRICS/metric_key, rank 지그 열, 설정 4곳, services/schemas, 메시지, openapi, stages 통합 코드(Core 미병합 상태로 작성), report 1줄
- 남음: 시험(test_jig_surf, test_rank_metric 추가, test_jig_stages, backend test_doe_config·test_doe_rank_metric_api), Core 병합 후 통합 시험, 전체 pytest, openapi --check
- stages 의 fit_report weights 인수(w_fit_full) 는 Core 시그니처 확인 후 맞출 것
- 시험 환경: source /tmp/rdenv_jigbe.sh (PY=/tmp/rdvenv/bin/python), postgres 는 su postgres -c "pg_ctl -D /tmp/rdpg/data -o '-p 54329 -k /tmp' -l /tmp/rdpg/log start"
