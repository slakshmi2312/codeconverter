import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 22000,
});

export async function convertCode(payload) {
  const response = await api.post("/convert", payload);
  return response.data;
}

export async function compileCode(payload) {
  const response = await api.post("/compile", payload);
  return response.data;
}
