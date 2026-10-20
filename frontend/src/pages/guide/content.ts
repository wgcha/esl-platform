// 사용 가이드 내용(계약 esl_p3_ux.md §4·§6·§8). 같은 내용 문서: docs/manual/user.md — 카드 제목을 바꾸면 그쪽도 같이(시험이 대조).

/** 바로가기 대상. 프로젝트·Case 가 필요한 곳은 화면이 최근 연 Case 로 채운다 */
export type GuideTarget =
  | { kind: "cases" }
  | { kind: "new" }
  | { kind: "stage"; n: number }
  | { kind: "library" }
  | { kind: "analysisNew" }
  | { kind: "comparisonNew" }
  | { kind: "updates" }
  | { kind: "none" };

export interface GuideCard {
  id: string;
  title: string;
  /** 한 줄 요약(이 단계가 하는 일) */
  what: string;
  steps: string[];
  /** 판단 기준(결과를 보고 다음으로 넘어가도 되는지) */
  check?: string[];
  tip?: string;
  target: GuideTarget;
  label: string;
}

export interface GuideGroup {
  id: string;
  title: string;
  cards: GuideCard[];
}

export const GUIDE_FLOW = ["rad + h3d 올리기", "① 추출", "② t*", "③ 지지점", "④ ESL", "⑤ 검증", "⑥ 내보내기", "라이브러리"];

export const GUIDE: GuideGroup[] = [
  {
    id: "start",
    title: "시작하기",
    cards: [
      {
        id: "case",
        title: "Case란",
        what: "낙하 씬 1개를 분석하는 단위입니다. Case 1개 = h3d 1개 + rad(include 포함) + 대상 파트 1개.",
        steps: [
          "①~⑥ 단계의 결과가 Case 폴더 하나(01_extract … 06_export, 보고서)에 차례로 쌓입니다.",
          "앞 단계를 바꾸면 뒤 단계에 '이전 단계가 바뀌었습니다' 표시가 뜹니다 — 그 단계부터 다시 실행하세요.",
          "같은 제품의 여러 씬은 Case를 여러 개 만들고, 검증된 결과를 라이브러리에 모아 함께 봅니다.",
        ],
        target: { kind: "cases" },
        label: "Case 목록 열기",
      },
      {
        id: "new-case",
        title: "새 Case — 내 PC에서 올리기",
        what: "기본 방법. rad·include와 h3d를 브라우저로 서버에 올리면 서버가 h3d에서 필요한 값을 직접 추출합니다.",
        steps: [
          "Case 목록에서 '새 Case' → '내 PC에서 올리기' 탭.",
          "① rad·include: _0000.rad 과 include 파일을 고르거나 폴더째 끌어다 놓습니다.",
          "② h3d 결과 파일 1개를 고릅니다(수 GB~수십 GB). '올리기'를 누르면 속도와 남은 시간이 보입니다.",
          "끊기거나 탭을 닫았으면 같은 파일을 다시 고르고 '올리기'(이어 올리기) — 서버가 받은 데부터 계속합니다.",
          "확인 결과에 include가 빠졌다고 나오면 '추가로 올리기'로 그 파일만 더 올립니다.",
          "Case 이름·대상 파트(기본 chassis_rear)를 확인하고 'Case 만들기'.",
        ],
        tip: "h3d가 매우 크면(수십 GB) PC에서 ESL_extract.bat으로 추출해 결과 폴더(수백 MB)만 올리는 것이 빠릅니다 — 아래 'PC에서 h3d 추출(대안)'. 참고: 30 GB는 1 Gbps에서 약 5분, 100 Mbps에서 약 45분.",
        target: { kind: "new" },
        label: "새 Case 열기",
      },
      {
        id: "server-folder",
        title: "새 Case — 서버 폴더에서 고르기",
        what: "이미 서버 업로드 폴더에 있는 rad·h3d(또는 추출 결과 폴더)를 다시 쓸 때.",
        steps: [
          "'서버 폴더에서 고르기' 탭에서 폴더 이름을 눌러 들어갑니다.",
          "rad 파일 옆 'rad 선택', h3d 파일 옆 'h3d 선택'(또는 done.json이 있는 폴더 옆 '결과 폴더 선택') 배지를 누릅니다.",
          "rad 확인 표에서 대상 파트가 있는지 보고 'Case 만들기'.",
          "경로를 직접 붙여 넣어야 할 때만 '고급: 경로 직접 입력'을 펼칩니다.",
        ],
        tip: "내 PC의 경로(예 F:\\Hyper_work)는 서버에서 보이지 않습니다. 서버 폴더 탭에는 서버에 올라온 파일만 보입니다.",
        target: { kind: "new" },
        label: "새 Case 열기",
      },
      {
        id: "pc-extract",
        title: "PC에서 h3d 추출(대안)",
        what: "h3d가 아주 크거나 망이 느릴 때. 내 PC의 HyperView로 필요한 값만 뽑아 수백 MB 결과 폴더로 만듭니다.",
        steps: [
          "저장소 클론 폴더의 update.bat 을 더블클릭해 PC 도구(ESL_extract.bat)를 설치·갱신합니다(서버용 deploy\\update.bat 과 다른 파일).",
          "h3d 파일을 ESL_extract.bat 위로 끌어다 놓습니다 → <작업 폴더>\\<h3d 이름>\\csv\\ 에 결과 폴더(done.json·CSV)가 생깁니다.",
          "새 Case → '내 PC에서 올리기' → '추출 결과가 이미 있으면'을 펼쳐 그 폴더를 고르고 rad·include와 함께 올립니다.",
        ],
        tip: "다른 파트를 뽑으려면 명령창에서 ESL_extract.bat <h3d> <파트 이름|ID>.",
        target: { kind: "new" },
        label: "새 Case 열기",
      },
    ],
  },
  {
    id: "stages",
    title: "①~⑥ 단계",
    cards: [
      {
        id: "s1",
        title: "① 입력·추출",
        what: "h3d에서 대상 파트의 메시·변위·변형률 이력을 읽어 Case 폴더(01_extract)에 정리합니다. h3d는 읽기만 합니다.",
        steps: ["Case를 열면 ① 입력. rad·h3d 경로와 파트 확인 표를 봅니다.", "'추출 실행' → 오른쪽 대기열에서 진행을 봅니다(h3d 추출은 수 분~수십 분)."],
        check: ["파트 요소 수가 예상과 같은지(예 chassis_rear 약 22만)", "프레임 수·후보 프레임이 채워졌는지", "경고(include 누락, 파트 없음)가 없는지"],
        target: { kind: "stage", n: 1 },
        label: "① 입력 열기",
      },
      {
        id: "s2",
        title: "② t* (하중 시점)",
        what: "정적 하중으로 바꿀 순간 t*를 고릅니다. h3d의 Max_Strain·Plastic Strain은 요소별 누적 최대(max-hold)라, t* = 최종 최대값에 처음 도달한 프레임(first-reach)입니다.",
        steps: ["기본 지표 Max_Strain의 1순위 후보가 자동 선택됩니다.", "이력 곡선과 후보 표(요소·값·시각)를 보고 필요하면 다른 후보를 고른 뒤 't* 확정'."],
        check: ["곡선이 t* 이후 평평한지(그 뒤로 최대값이 더 오르지 않음)", "1순위 요소가 실제 관심 부위(파손·고변형 위치)인지", "Plastic Strain 결과도 비슷한 시점인지"],
        target: { kind: "stage", n: 2 },
        label: "② t* 열기",
      },
      {
        id: "s3",
        title: "③ 지지점 (3-2-1)",
        what: "파트를 자유물체로 보고 강체 운동 6자유도만 막는 3-2-1 정정 구속점 3개를 정합니다. 하중이 자기평형이라 반력은 거의 0입니다.",
        steps: ["PCA 평면 산점도에 자동 추천 노드 3개가 표시됩니다.", "그대로 두거나 노드 ID를 바꾼 뒤 '지지점 저장'."],
        check: ["세 노드가 넓게 퍼지고 한 줄에 놓이지 않았는지", "고변형 부위(핫스팟)에서 떨어져 있는지", "파트 밖 노드가 아닌지(오류 NODE_NOT_IN_PART)"],
        target: { kind: "stage", n: 3 },
        label: "③ 지지점 열기",
      },
      {
        id: "s4",
        title: "④ ESL 계산",
        what: "t* 변위에서 강체 운동을 빼고(u_rel) 절점 등가하중 F_eq를 계산합니다.",
        steps: ["'ESL 계산' → 강체 회전각, ΣF·ΣM·평형 오차, 잡음 지표, F_eq 상위 노드 표를 봅니다."],
        check: [
          "평형 오차 |ΣF|/Σ|F| ≤ 1e-6 (자기평형)",
          "강체 제거 품질 OK(WARN이면 변형이 아주 큰지 확인)",
          "잡음 경고 없음 — h3d 변위가 float32라 변형이 작으면 F_eq가 잡음에 묻힙니다(검증에서 NOISE_FLOOR FAIL)",
          "F_eq 상위 노드가 충돌·접촉 부위와 맞는지",
        ],
        target: { kind: "stage", n: 4 },
        label: "④ ESL 열기",
      },
      {
        id: "s5",
        title: "⑤ 검증",
        what: "F_eq를 정적 해석으로 다시 풀어 원래 낙하 해석의 변형률을 얼마나 재현하는지 봅니다.",
        steps: ["'검증 실행' → PASS/FAIL 배지, 오차 요약, 히스토그램, 겹쳐보기(원래 vs ESL 분포·단면).", "끝나면 Case 보고서(HTML)가 자동으로 만들어집니다 — '보고서 보기'."],
        check: [
          "최대변형률 오차 ≤ 10% (설정 compare.max_err_pct_max)",
          "요소별 오차 P90 ≤ 20% (compare.p90_err_max)",
          "잡음 지표 ≤ 5% (noise_strain_rel_max) — 넘으면 NOISE_FLOOR FAIL",
          "겹쳐보기에서 고변형 위치·모양이 같은지",
        ],
        tip: "FAIL이면 ② t* 후보나 ③ 지지점을 바꿔 다시 계산해 봅니다. FAIL 결과도 사유를 적어 라이브러리에 '확정' 등록할 수 있습니다.",
        target: { kind: "stage", n: 5 },
        label: "⑤ 검증 열기",
      },
      {
        id: "s6",
        title: "⑥ 내보내기 · 결과 받기",
        what: "F_eq와 3-2-1 구속을 해석 입력 파일로 씁니다: Radioss inc(/CLOAD·/BCS), OptiStruct fem, CSV.",
        steps: [
          "대상을 고르고 '내보내기' → 06_export 아래 파일이 생깁니다.",
          "'결과 받기(zip)'로 내보내기 파일·보고서·요약 json·csv를 한 번에 내 PC로 받습니다(Case 상단 메뉴에도 있음).",
          "zip이 너무 크면(기본 5 GB 초과) 폴더 경로가 표시됩니다 — '경로 복사' 후 탐색기에서 여세요.",
        ],
        target: { kind: "stage", n: 6 },
        label: "⑥ 내보내기 열기",
      },
    ],
  },
  {
    id: "library",
    title: "라이브러리",
    cards: [
      {
        id: "lib-register",
        title: "라이브러리 등록",
        what: "검증 PASS 결과를 제품·씬 정보와 함께 모아 둡니다(등록 시 스냅샷 고정).",
        steps: ["⑤ 검증 화면의 '라이브러리 등록' → 모델·인치·버전·씬 정보를 확인·입력.", "고칠 일이 생기면 새로 등록하고 이전 항목은 폐기(retire)합니다."],
        target: { kind: "stage", n: 5 },
        label: "⑤ 검증 열기",
      },
      {
        id: "lib-analysis",
        title: "종합분석 · 비드 덱",
        what: "여러 씬의 F_eq를 묶어 대표 하중 케이스를 고르고 셀 합력 포락을 보며, OptiStruct 비드 최적화 덱(모든 씬 minmax)을 만듭니다.",
        steps: ["라이브러리 → '종합분석 만들기' → 설계 대상·필터·정규화 고르고 실행.", "상세에서 대표 케이스·포락·덱 정보 확인, '보고서 보기'·'결과 받기(zip)'."],
        tip: "덱은 내 PC/HPC에서 OptiStruct로 실행합니다 — 먼저 optistruct -check 로 문법을 확인하세요.",
        target: { kind: "analysisNew" },
        label: "종합분석 만들기",
      },
      {
        id: "lib-compare",
        title: "설계 버전 비교",
        what: "같은 모델의 두 설계 버전(예 v072 → v073)을 같은 씬끼리 짝지어 하중·변형률 변화를 봅니다.",
        steps: ["라이브러리 → '버전 비교' → 모델·기준 버전·새 버전 선택 후 실행.", "판정 배지와 씬별 표, 보고서로 개선·악화를 확인합니다."],
        target: { kind: "comparisonNew" },
        label: "버전 비교 만들기",
      },
    ],
  },
];

export interface Faq {
  q: string;
  a: string;
}

export const FAQ: Faq[] = [
  {
    q: "회사 PC에서 '대시보드 계정이 활성 상태가 아닙니다'가 떠요",
    a: "회사 프록시가 서버 내부 호출을 가로채던 문제로 v0.4.0에서 고쳤습니다. 계속되면 브라우저 프록시 예외에 서버 주소를 넣고, 관리자에게 서버 로그의 403 사유를 확인해 달라고 하세요.",
  },
  { q: "'새 Case'·주 버튼이 회색이에요", a: "프로젝트 역할이 '조회(general)'이면 실행할 수 없습니다. 버튼에 마우스를 올리면 사유가 보입니다. 대시보드 관리자에게 '실행(power)' 역할을 요청하세요." },
  {
    q: "업로드가 끊겼어요 / 탭을 닫았어요",
    a: "같은 파일을 다시 고르고 '올리기'를 누르면 서버가 받은 데부터 이어 올립니다(파일 이름·크기·수정 시각이 같아야 함). 청크마다 sha256을 확인하므로 손상된 부분은 다시 보냅니다.",
  },
  {
    q: "용량 한도가 얼마예요? '저장 공간 부족'이 떠요",
    a: "기본 파일당 64 GB, 업로드당 100 GB입니다. 서버 여유 공간이 모자라면 시작 전에 '저장 공간 부족(507)'으로 막습니다 — 관리자에게 알리거나 PC에서 추출한 결과 폴더(수백 MB)만 올리세요.",
  },
  { q: "결과 받기(zip)가 안 되고 경로만 보여요", a: "zip이 한도(기본 5 GB)를 넘었습니다. 경로를 복사해 탐색기로 여세요. 대용량 원자료(npz)는 기본으로 zip에서 빠집니다." },
  {
    q: "환경 점검에 CHOLMOD SKIP이 보여요",
    a: "정상입니다. CHOLMOD(scikit-sparse)는 Windows용 설치 파일이 없어 건너뛰고, Windows 서버는 PARDISO(MKL) 솔버를 씁니다. 솔버 이름은 오른쪽 '워커' 패널에 보입니다.",
  },
  { q: "단계에 '이전 단계가 바뀌었습니다'가 떠요", a: "앞 단계(t*·지지점 등)를 바꿔 지금 결과가 옛 입력 기준입니다. 그 단계의 주 버튼으로 다시 실행하세요." },
  { q: "보고서 버튼이 비활성이에요", a: "Case 보고서는 ⑤ 검증이 끝나면 자동으로 만들어집니다. 검증을 먼저 실행하세요." },
  { q: "새 버전이 나왔는지 어떻게 알아요?", a: "상단 바 버전(v0.4.0) 옆에 점이 보이면 마지막으로 본 뒤 업데이트가 있었다는 뜻입니다. 누르면 업데이트 내역이 열립니다." },
];
