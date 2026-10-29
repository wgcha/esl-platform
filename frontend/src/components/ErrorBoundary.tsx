// 화면 렌더 예외 경계(v0.7.2): 빈 화면 대신 "화면 오류: <메시지> [다시 시도]" 한 줄. 스택은 콘솔에만.
// App 최상위(셸 포함)와 페이지 단위(Routes, 경로가 바뀌면 resetKey 로 자동 해제) 두 겹으로 쓴다.
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** 값이 바뀌면 오류 상태를 지운다(예: 경로) */
  resetKey?: string;
}
interface State {
  error: Error | null;
  key?: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, key: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  static getDerivedStateFromProps(p: Props, s: State): Partial<State> | null {
    return p.resetKey !== s.key ? { error: null, key: p.resetKey } : null;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ESL] 화면 오류:", error, info.componentStack);
  }

  render() {
    const e = this.state.error;
    if (!e) return this.props.children;
    return (
      <div className="error-text screen-error" role="alert" data-testid="screen-error">
        화면 오류: {e.message || String(e)}{" "}
        <button type="button" className="btn small" onClick={() => this.setState({ error: null })}>
          다시 시도
        </button>
      </div>
    );
  }
}
