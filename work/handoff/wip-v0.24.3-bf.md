# WIP v0.24.3 묶음 B(백엔드)+C(프런트)

- 브랜치 wip/v0.24.3-bf (계약 커밋 d1eb8927 분기). push 금지.
- B 완료: results 서비스·라우터(`?src=`·/sources·이력), schemas 4개, core_outputs.validation_fields, register.py 리팩터, openapi 덤프, backend/tests/test_val_src_api.py(11). backend pytest 989 통과.
- C 완료(구현): Stage5 탭·mark·빈 탭 버튼·info 반력·이력, sources.ts(tabItemsOf·valTabItems·markOf), SourceTabs mark, DispOverlay/FieldOverlay/SectionChart src, api endpoints·types, mock(valsrcmock.ts·server.ts·install `?demoValSrc=ok|notrun`), __tests__/val_src.test.tsx(15).
- 완료: vitest 722 통과, typecheck·build·check:api 통과, Playwright 높이 동일(shots/v0243_*.png). 남음: 통합(A 합류 후 실제 esl.val_src 로 시험).
- 가정(A 산출물): `esl.val_src.VAL_PLAN`(행 key·legacy·load·dir·na)·`REASON_TEXT`, 05_val/sources.json(§6.2), 05_val/<dir>/validation.json 등(§6.3). 백엔드는 core_adapter._attr 로 읽음 — A 의 어댑터 래퍼로 교체 가능.
- 시험 환경: `source /tmp/rdenv_bf.sh`(REPO_ROOT=이 트리), PG: su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/rdpg/data -o '-p 54329 -k /tmp' -l /tmp/rdpg/log5.txt start".
