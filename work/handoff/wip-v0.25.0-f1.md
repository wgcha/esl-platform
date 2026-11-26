# wip v0.25.0 F1 (프런트 — 추가 비드 kind "A") handoff

브랜치 wip/v0.25.0-f1 (기준 release/v0.25.0 59c81863). 소유 범위 frontend/** 만. 계약 docs/contracts/esl_virtual_bead.md §9·§19·§19.9, VB-1~28.

## 한 일
- `view3d/select/basis.ts`: BasisVar += form/g/c, `ramp`·`depthEff`·`termAt`(코어 식), parseBasis 가 hinge 꼬리 [g:f32×n] 읽음(길이 엄격·c 없음 오류), writeBasis g, morph·heightChange 가 termAt, beadDirections 가 A 포함.
- `view3d/select/vbead.ts`(신규 순수): 입력 칸·검사(θ 15~60·길이·각도·깊이 한도·r)·요청 만들기((a) 두 점/(b) 좌표, flip true 만 키, r 준 값이면 0 도 키, side 없음)·ξη 환산·행 문구·previewVar·3D 선분.
- `layers.ts`: SelState.vbeads(schema 2), snap/restore(실행 취소)·clone·reset·toSelectionAny(없음/빈 = 키 없음)·fromSelectionIn, addVBead/removeVBead.
- `BeadSelectCard.tsx`: ctrl.vb(VbCtrl), 3D 두 점 찍기(host 면 판정 `isVbHostElem`, 아니면 "평판 위를 찍으세요"), 빨강 점·발자국 윤곽 겹쳐 그리기, 추가/삭제 뒤 250 ms 디바운스 자동 derive, vbeads 만 있는 선택 허용, `MorphStage` 추출(SelectDesign3D 는 감쌈 — DOM 불변).
- `VirtualBeadPanel.tsx`(신규)·BeadList: 접힌 절 "추가 비드(평판에 새 비드)" — 라디오 2(입력 방식)·ξ η 길이 각도·D W θ 끝 r·체크 "방향 뒤집기" 1개·[비드 추가], 행(상태·⚠·r·평탄부·[삭제]), 활성 행 = 깊이 슬라이더 + MorphStage.
- `DoeParamTable`: kind virtual 가지(머리 "A1 추가 비드 1 · W 20 · θ 45° · L 120", 라벨 `label`, 행 툴팁 사면 요소·예상 오차, 거부 = 회색 "추가 불가 · 문구"), 회색 꼬리표 "뒤틀림 n"(`doe-tag-info`), A 행 있으면 `.table-wrap.scroll`. `doe.ts`: TYPE_NAME.A, defaultRows(hinge), rowProblem A, warpTag·vbRowTip·VB_TEXT, settings `virtual_bead` 정규화. DoeStudy 계획 칩 `A1 0`.
- mock: `?demoVBead=1`(설정 켬) + 목 derive/params/basis(hinge). 시험: `__tests__/vbead_basis.test.ts`(코어 fixture 동등 18), `vbead_ui.test.tsx`(7). fixture = `fixtures/vbead_hinge_core.json`(코어 field+hinge 로 생성).
- 증적 스크립트 `scripts/screenshots-v0250-f1.mjs`.

## B1 과 맞춰야 할 키 (check:api 는 통합 때 openapi 와 대조 — 지금은 TS 에만 있는 키 4건으로 실패가 정상)
- `SelectionInV2.virtual_beads: VirtualBeadIn[]`(types.ts 이름 `VirtualBeadIn` — openapi 스키마 이름이 다르면 통합 때 types 쪽을 맞춤), `flip: true`, `r`(0 포함), `side` 없음.
- `SelectionDerived.virtual_beads[]`(= §19.7 키 전부, `outline_ab`·`preview{idx,vec,g,c}`·`r_resolved`·`r_source`·`host`·`side_resolved`), `vb_frame{origin,e_xi,e_eta,n_h}`.
- `GET /doe/settings` `virtual_bead{enabled,max_count,theta_default_deg,theta_range_deg,d_max_limit_mm,min_wall_elems,r_default_h_mult}` — **enabled 가 true 일 때만 절을 보임**(없으면 숨김). 스냅샷에 블록이 없는 스터디에서 숨기려면 B1 이 settings 대신 스터디 단위로 줘야 함(지금은 설정 기준).
- params: A 행 `form "hinge"`·`label`·`wall_elems`·`vb`·`acc_hint`·`guard.warp{limit_deg,n,max_deg,at,text?}`, beads[] `kind "virtual"`·`vb_reason{code,text}`·`warnings[].text`. basis.json vars[] `form:"hinge"`·`c`, basis.bin hinge = vec 뒤 g 꼬리.

## 계약과 다르게 한 점
- ξ·η 칸 ↔ 모델 좌표: derive 의 `vb_frame`(첫 추가 비드 전에는 없음)이 오기 전에는 그래프 frame(e1·e2·origin, 판 높이 = 노드 법선 성분 중앙값)으로 환산 — 두 frame 이 같다고 가정(어긋나면 사유 VB_NOT_ON_PLATE 로 드러남). 각도는 환산 없이 그대로 전송.
- 설정 키가 없으면 절 숨김(스냅샷 블록 유무는 프런트가 모름).
- 새 버튼은 [비드 추가]·[삭제](행 ✕)뿐 — 행 클릭 = 활성 + 입력 칸 복원(flip 포함), 편집 버튼 없음.

## 화면(mock, 2560·1920)
- 설정 끔(base 와 대조): 새 스터디·doe-10 scrollHeight·③ 카드 높이 ±0. 설정 켬: 접힌 절 +21 px(2560)·+18 px(1920)(③ 카드 안, 페이지 scrollHeight 는 ±0 — 카드 안 스크롤), 펼침 133/161 px, 비드 1개 + 미리보기 활성 시 절 약 958/822 px, 가로 스크롤 없음.
