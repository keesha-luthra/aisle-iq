import { useState, useEffect } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export function useApi(storeId) {
  const [data, setData] = useState({
    health: null,
    metrics: null,
    cameraAnalytics: null,
    heatmap: null,
    funnel: null,
    anomalies: []
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    const fetchData = async () => {
      try {
        const [healthRes, metricsRes, camRes, heatRes, funnelRes, anomRes] = await Promise.all([
          fetch(`${API_BASE}/health`).catch(() => null),
          fetch(`${API_BASE}/stores/${storeId}/metrics?window_hours=720`).catch(() => null),
          fetch(`${API_BASE}/stores/${storeId}/camera-analytics`).catch(() => null),
          fetch(`${API_BASE}/stores/${storeId}/heatmap`).catch(() => null),
          fetch(`${API_BASE}/stores/${storeId}/funnel?window_hours=720`).catch(() => null),
          fetch(`${API_BASE}/stores/${storeId}/anomalies`).catch(() => null)
        ]);

        if (mounted) {
          setData({
            health: healthRes?.ok ? await healthRes.json() : null,
            metrics: metricsRes?.ok ? await metricsRes.json() : null,
            cameraAnalytics: camRes?.ok ? await camRes.json() : null,
            heatmap: heatRes?.ok ? await heatRes.json() : null,
            funnel: funnelRes?.ok ? await funnelRes.json() : null,
            anomalies: anomRes?.ok ? (await anomRes.json()).anomalies : []
          });
          setLoading(false);
        }
      } catch (err) {
        console.error("API Fetch Error", err);
        if (mounted) setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 15000); // Polling every 15s

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [storeId]);

  return { data, loading };
}
