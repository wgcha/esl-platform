# wip v0.25.1 F1c — 2D·썸네일·높이 변화 범례 색 통일
- DispOverlay·FieldOverlay·library/common = css/cssGradient(mapFor seq|div), NaN = specialCss("nan").
- BeadSelectCard.HeightLegend: 새 = "빨강 = 깊어짐 · 파랑 = 얕아짐"(띠 div), `legacy` = 옛 문구 + 반전 띠. DoeThumbGrid: color.map !== "diverge" → legacy.
- mock: selThumbSvg = div 지도, doedata 미리보기 color.map "diverge".
- shim(VIRIDIS·DIVERGING·NA_COLOR·lerp·gradient·DIVERGING_GRADIENT)·colors.ts 재내보냄 삭제, V-0251-37 허용 목록 비움.
- 시험: __tests__/color_f1c.test.tsx
