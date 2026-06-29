import { invokeWithAuth } from '@/lib/tokenStore';

export interface EnvVariable {
  key: string;
  value: string;
  description: string;
}

export interface EnvConfig {
  backend_vars: Record<string, EnvVariable>;
  frontend_vars: Record<string, EnvVariable>;
}

export interface EnvVariableUpdate {
  value: string;
}

export interface AiSettings {
  enabled: boolean;
  provider: string;
  base_url: string;
  model: string;
  api_key_set: boolean;
  api_key_preview: string;
  source: string;
  updated_at?: string | null;
}

export interface AiSettingsUpdate {
  enabled: boolean;
  provider?: string;
  api_key?: string;
  clear_api_key?: boolean;
  base_url: string;
  model: string;
}

export const settingsApi = {
  // Fetch all configurations
  async getConfig(): Promise<EnvConfig> {
    const response = await invokeWithAuth({
      url: '/api/v1/admin/settings',
      method: 'GET',
    });
    return response.data;
  },

  // Update backend configuration
  async updateBackendConfig(
    key: string,
    value: string
  ): Promise<{ message: string }> {
    const response = await invokeWithAuth({
      url: `/api/v1/admin/settings/backend/${key}`,
      method: 'PUT',
      data: { value },
    });
    return response.data;
  },

  // Update frontend configuration
  async updateFrontendConfig(
    key: string,
    value: string
  ): Promise<{ message: string }> {
    const response = await invokeWithAuth({
      url: `/api/v1/admin/settings/frontend/${key}`,
      method: 'PUT',
      data: { value },
    });
    return response.data;
  },

  // Add backend configuration
  async addBackendConfig(
    key: string,
    value: string
  ): Promise<{ message: string }> {
    const response = await invokeWithAuth({
      url: `/api/v1/admin/settings/backend/${key}`,
      method: 'POST',
      data: { value },
    });
    return response.data;
  },

  // Add frontend configuration
  async addFrontendConfig(
    key: string,
    value: string
  ): Promise<{ message: string }> {
    const response = await invokeWithAuth({
      url: `/api/v1/admin/settings/frontend/${key}`,
      method: 'POST',
      data: { value },
    });
    return response.data;
  },

  // Delete backend configuration
  async deleteBackendConfig(key: string): Promise<{ message: string }> {
    const response = await invokeWithAuth({
      url: `/api/v1/admin/settings/backend/${key}`,
      method: 'DELETE',
    });
    return response.data;
  },

  // Delete frontend configuration
  async deleteFrontendConfig(key: string): Promise<{ message: string }> {
    const response = await invokeWithAuth({
      url: `/api/v1/admin/settings/frontend/${key}`,
      method: 'DELETE',
    });
    return response.data;
  },

  async getAiSettings(): Promise<AiSettings> {
    const response = await invokeWithAuth({
      url: '/api/v1/admin/ai-settings',
      method: 'GET',
    });
    return response.data;
  },

  async updateAiSettings(data: AiSettingsUpdate): Promise<AiSettings> {
    const response = await invokeWithAuth({
      url: '/api/v1/admin/ai-settings',
      method: 'PUT',
      data,
    });
    return response.data;
  },

  async testAiSettings(): Promise<{ ok: boolean; model: string; message: string }> {
    const response = await invokeWithAuth({
      url: '/api/v1/admin/ai-settings/test',
      method: 'POST',
    });
    return response.data;
  },
};
