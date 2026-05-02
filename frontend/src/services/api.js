import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 65000);

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: API_TIMEOUT_MS,
});

function getApiErrorMessage(error, fallbackMessage) {
  if (error?.code === "ECONNABORTED") {
    return `Request timed out after ${API_TIMEOUT_MS}ms. Please try again.`;
  }

  if (error?.response?.data?.detail) {
    return error.response.data.detail;
  }

  return error?.message || fallbackMessage;
}

export async function convertCode(payload) {
  try {
    const response = await api.post("/convert", payload);
    return response.data;
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Conversion failed."));
  }
}

export async function runCode(payload) {
  try {
    const response = await api.post("/run", payload);
    return response.data;
  } catch (error) {
    throw new Error(getApiErrorMessage(error, "Run failed."));
  }
}
