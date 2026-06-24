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
};
