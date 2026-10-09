
const API_BASE_URL = "http://127.0.0.1:8000";

export interface SilveraStatus {
  name: string;
  status: string;
  message: string;
}

export async function getSilveraStatus(): Promise<SilveraStatus> {
  const response = await fetch(`${API_BASE_URL}/api/status`);

  if (!response.ok) {
    throw new Error("Could not connect to Silvera's backend.");
  }

  return response.json();
}
