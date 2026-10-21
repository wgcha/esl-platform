/** /PART title 비교용 정규화: 공백·'_'·'-' 연속을 한 칸으로, 대소문자 무시(백엔드 exact_ci 와 같은 규칙) */
export const normPartTitle = (t: string): string => t.replace(/[\s_-]+/g, " ").trim().toLowerCase();
