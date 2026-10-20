import type { RadPart } from "../../api/types";

/** §6 새 Case 입력: rad 필수 + h3d(서버 추출, 기본) 또는 추출 결과 폴더 중 하나 */
export type InputSource = { kind: "h3d"; path: string } | { kind: "results"; path: string };

export interface InputSelection {
  rad_path: string;
  source: InputSource;
  parts: RadPart[];
  ok: boolean;
}
