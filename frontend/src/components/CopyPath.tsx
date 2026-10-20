import { useState } from "react";

export const TOO_LARGE_TEXT = "파일이 커서 다운로드 대신 경로를 복사하세요";

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** 경로 표시 + 복사 버튼(PhysicsAI CodeLine·CopyButton 과 같은 모양) */
export function CopyPath({ path, testId }: { path: string; testId?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="codeline">
      <code data-testid={testId}>{path}</code>
      <button
        type="button"
        className="btn small ghost"
        onClick={async () => {
          if (await copyText(path)) {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }
        }}
      >
        {copied ? "복사됨" : "경로 복사"}
      </button>
    </div>
  );
}

