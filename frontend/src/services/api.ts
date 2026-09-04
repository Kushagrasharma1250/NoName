import axios from 'axios';
import { EventSummary, EventDetail, SystemStatistics, PersistentEvent } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 75000,
});

export interface RealtimeStatus {
  configured: boolean;
  source: string;
  last_success: string | null;
  last_error: string | null;
  fetched_count: number;
  stale: boolean;
  age_seconds: number | null;
}

export const fetchHealth = async (): Promise<boolean> => {
  try {
    const res = await api.get('/health');
    return res.data?.status === 'healthy';
  } catch {
    return false;
  }
};

export const fetchRealtimeStatus = async (): Promise<RealtimeStatus> => {
  const res = await api.get('/realtime/status');
  return res.data;
};

export const refreshRealtimeData = async (): Promise<RealtimeStatus> => {
  const res = await api.post('/realtime/refresh');
  return res.data;
};

export const fetchStatistics = async (): Promise<SystemStatistics> => {
  const res = await api.get('/statistics');
  return res.data;
};

export const fetchEvents = async (): Promise<EventSummary[]> => {
  const res = await api.get('/events');
  return res.data.events || [];
};

export const fetchPersistentEvents = async (): Promise<PersistentEvent[]> => {
  const res = await api.get('/events/persistent');
  return res.data.events || [];
};

export const fetchEventDetail = async (eventId: string): Promise<EventDetail> => {
  const res = await api.get(`/events/${eventId}`);
  return res.data;
};
