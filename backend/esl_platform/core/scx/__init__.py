"""SCX 릴레이 연결 계층(계약 esl_scx_relay.md SR-D-1) — 백엔드·워커 공용.

- `settings`: 설정 변환·검사(hpc.scx → 어댑터 ScxConfig, client_name·scx_drive.*).
- `gateway`: 어댑터 확인(SCX_ADAPTER_MISSING), `EslScxGateway`(client_name esl), 프로세스당 1개.
- `status`: 기능별 사용 가능 판정·사유(SR-D-19), 헬스 TTL 캐시.
- `messages`: 오류 → esl 코드·사용자 문구(resources/scx_messages.json).
- `mask`: 비밀·토큰·서버 경로 마스킹, 로그 필터.
- `paths`: 드라이브 경로 규칙(루트·SPDM·relay_base).

백엔드는 가벼운 호출만(health·list), 내려받기는 워커 XFER 작업만. 어댑터는 이 패키지 안에서만 import 한다.
"""
