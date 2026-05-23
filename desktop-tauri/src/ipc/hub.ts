import { invoke } from '@tauri-apps/api/core';

export type LoginResult = {
  user: Record<string, unknown>;
  token: { id: number; token: string; label: string; created_at: string };
};

export async function hubHealthz(url: string, token: string): Promise<Record<string, unknown>> {
  return invoke<Record<string, unknown>>('hub_healthz', { url, token });
}

export async function hubLogin(url: string, username: string, password: string): Promise<LoginResult> {
  return invoke<LoginResult>('hub_login', { url, username, password });
}

export async function hubListSessions(url: string, token: string): Promise<Record<string, unknown>[]> {
  return invoke<Record<string, unknown>[]>('hub_list_sessions', { url, token });
}

export async function hubUpload(url: string, token: string, sessionId: string): Promise<Record<string, unknown>> {
  return invoke<Record<string, unknown>>('hub_upload', { url, token, sessionId });
}

export async function hubShare(url: string, token: string, sessionId: string): Promise<Record<string, unknown>> {
  return invoke<Record<string, unknown>>('hub_share', { url, token, sessionId });
}
