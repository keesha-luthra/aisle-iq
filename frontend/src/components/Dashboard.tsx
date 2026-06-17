import React, { useState } from 'react';
import { useApi } from '../hooks/useApi';
import MetricCard from './MetricCard';
import VideoPanel from './VideoPanel';
import HeatmapChart from './HeatmapChart';
import FunnelChart from './FunnelChart';
import InsightsPanel from './InsightsPanel';

const ALL_CAMS = ["CAM_01", "CAM_02", "CAM_03", "CAM_05"];
const CAM_LABELS = {
  "STORE_BLR_002": {
      "CAM_01": "CAM 1 - Zone Floor (North)",
      "CAM_02": "CAM 2 - Zone Floor (South)",
      "CAM_03": "CAM 3 - Entry / Exit Gate",
      "CAM_05": "CAM 5 - Billing & Checkout",
  },
  "STORE_MUM_076": {
      "CAM_01": "CAM 1 - Shop Floor Zone",
      "CAM_02": "CAM 2 - Entry Door 2",
      "CAM_03": "CAM 3 - Entry Door 1",
      "CAM_05": "CAM 5 - Billing Area",
  },
};

export function Dashboard() {
  const [selectedStore, setSelectedStore] = useState('STORE_BLR_002');
  const { data, loading } = useApi(selectedStore);

  const metrics = data?.metrics || {};
  const cameraAnalytics = data?.cameraAnalytics || {};
  const camerasStats = cameraAnalytics.cameras || {};

  return (
    <div id="dashboard" className="w-full bg-[#030303] text-white py-16 px-6 md:px-12 lg:px-16 font-sans relative z-20">
      <div className="max-w-7xl mx-auto">
        <div className="mb-12 flex flex-col md:flex-row md:items-end justify-between gap-4">
          <div>
            <h2 className="text-3xl md:text-4xl font-light mb-2">Store Intelligence</h2>
            <p className="text-gray-400 text-sm md:text-base">Real-time metrics and spatial analysis for {selectedStore}.</p>
          </div>
          <select 
            value={selectedStore} 
            onChange={(e) => setSelectedStore(e.target.value)}
            className="bg-[#111] border border-white/20 text-white text-sm rounded-lg focus:ring-white/50 focus:border-white/50 block p-3 outline-none cursor-pointer"
          >
            <option value="STORE_BLR_002">Brigade Road, BLR</option>
            <option value="STORE_MUM_076">Bandra West, MUM</option>
          </select>
        </div>

        {/* Metrics Grid */}
        <div id="metrics" className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-12 scroll-mt-24">
          <MetricCard title="Unique Visitors" value={metrics.unique_visitors || 0} />
          <MetricCard title="Billing Visitors" value={cameraAnalytics.billing_visitors || 0} />
          <MetricCard title="Conversion Rate" value={`${(metrics.conversion_rate * 100 || 0).toFixed(1)}%`} />
          <MetricCard title="Peak Hour" value={cameraAnalytics.peak_traffic_hour || "N/A"} />
          <MetricCard title="Queue Depth" value={metrics.current_queue_depth || 0} />
          <MetricCard title="Abandonment" value={`${(metrics.abandonment_rate * 100 || 0).toFixed(1)}%`} />
        </div>

        {/* Charts & Insights */}
        <div className="grid lg:grid-cols-3 gap-6 mb-12">
          <div className="lg:col-span-2 grid md:grid-cols-2 gap-6">
            <div id="heatmaps" className="liquid-glass rounded-xl p-6 scroll-mt-24">
              <h3 className="text-lg font-medium mb-4">Traffic Heatmap</h3>
              <HeatmapChart data={data?.heatmap} />
            </div>
            <div id="funnel" className="liquid-glass rounded-xl p-6 scroll-mt-24">
              <h3 className="text-lg font-medium mb-4">Conversion Funnel</h3>
              <FunnelChart data={data?.funnel} />
            </div>
          </div>
          <div id="insights" className="liquid-glass rounded-xl p-6 scroll-mt-24">
            <h3 className="text-lg font-medium mb-4">Insights & Anomalies</h3>
            <InsightsPanel anomalies={data?.anomalies} />
          </div>
        </div>

        {/* Video Feeds */}
        <div id="camera-feeds" className="mb-8 scroll-mt-24">
          <h3 className="text-2xl font-light mb-6">Live Camera Feeds</h3>
          <div className="grid md:grid-cols-2 gap-6">
            {ALL_CAMS.map(camId => {
              const label = CAM_LABELS[selectedStore]?.[camId] || camId;
              const stats = camerasStats[camId] || {};
              const source = stats.active_visitors_count > 0 ? 'ANNOTATED' : 'RAW'; 

              return (
                <div key={camId} className="liquid-glass rounded-xl overflow-hidden p-1">
                  <VideoPanel 
                    camId={camId}
                    label={label}
                    source={source}
                    stats={stats}
                    selectedStore={selectedStore}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
