import { defineConfig, devices, type PlaywrightTestConfig } from '@playwright/test';
import { resolve } from 'node:path';
import { fakeMicPath } from './e2e/fake-mic';

const python = process.env.JAMRECALL_PYTHON ?? resolve(import.meta.dirname, '../backend/.venv/bin/python');
const backendDir = resolve(import.meta.dirname, '../backend');
export const E2E_DATA_ROOT = resolve(import.meta.dirname, 'test-results/e2e-data');
const mic = fakeMicPath();

// Each stack = isolated backend (own data dir + engine) + Vite dev server proxying to it.
// workflow: the real Basic Pitch engine (DR-0001). errors: the TEST-ONLY always-failing adapter.
const stacks = {
  workflow: { api: 8765, web: 5181, engine: process.env.JAMRECALL_E2E_ENGINE ?? 'basic-pitch' },
  errors: { api: 8766, web: 5182, engine: 'failing' },
};

const chromiumMic = (extra: string[] = []) => ({
  ...devices['Desktop Chrome'],
  channel: 'chromium', // full Chromium (new headless); the headless shell lacks media capture
  launchOptions: {
    args: [
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${mic}`,
      '--autoplay-policy=no-user-gesture-required',
      ...extra,
    ],
  },
});

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    {
      name: 'workflow',
      testMatch: /(workflow|annotation|playback)\.spec\.ts/,
      use: { ...chromiumMic(['--use-fake-ui-for-media-stream']), baseURL: `http://127.0.0.1:${stacks.workflow.web}` },
    },
    {
      name: 'errors',
      testMatch: /errors\.spec\.ts/,
      use: { ...chromiumMic(), baseURL: `http://127.0.0.1:${stacks.errors.web}` },
    },
  ],
  webServer: Object.entries(stacks).flatMap(([name, s]): NonNullable<PlaywrightTestConfig['webServer']> => [
    {
      command: `rm -rf "${E2E_DATA_ROOT}/${name}" && "${python}" -m uvicorn --factory jamrecall.app:get_app --host 127.0.0.1 --port ${s.api}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${s.api}/api/health`,
      env: {
        JAMRECALL_DATA_DIR: `${E2E_DATA_ROOT}/${name}`,
        JAMRECALL_TRANSCRIPTION_ENGINE: s.engine,
        JAMRECALL_ALLOW_TEST_ADAPTERS: s.engine === 'failing' || s.engine === 'fixture' ? '1' : '0',
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npx vite --port ${s.web}`,
      url: `http://127.0.0.1:${s.web}`,
      env: { JAMRECALL_API_URL: `http://127.0.0.1:${s.api}`, JAMRECALL_WEB_PORT: String(s.web) },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ]),
});
