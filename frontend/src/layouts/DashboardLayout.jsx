import React from 'react';

export default function DashboardLayout({ topnav, header, metrics, videoFeeds, charts, insights }) {
  return (
    <div className="dashboard-layout">
      {topnav}
      
      <div className="main-content">
        {header}
        
        <div className="metrics-grid">
          {metrics}
        </div>
        
        <div className="video-grid">
          {videoFeeds}
        </div>
        
        <div className="charts-grid">
          {charts}
        </div>
        
        <div style={{ marginTop: '16px' }}>
          <h3 style={{ marginBottom: '16px', fontSize: '1.2rem' }}>System Anomalies</h3>
          {insights}
        </div>
      </div>
    </div>
  );
}
