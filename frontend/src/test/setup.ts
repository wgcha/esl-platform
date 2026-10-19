import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

(globalThis as unknown as { __MOCK__: boolean }).__MOCK__ = false;
afterEach(() => cleanup());
