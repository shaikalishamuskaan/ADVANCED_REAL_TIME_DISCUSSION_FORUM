import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

import { beforeEach } from 'vitest';
beforeEach(() => {
  class QuietSocket {
    readyState = 0;
    onopen: ((event: unknown) => void) | null = null;
    onmessage: ((event: unknown) => void) | null = null;
    onclose: ((event: unknown) => void) | null = null;
    onerror: ((event: unknown) => void) | null = null;
    send() {}
    close() { this.readyState = 3; }
  }
  vi.stubGlobal('WebSocket', QuietSocket);
});
