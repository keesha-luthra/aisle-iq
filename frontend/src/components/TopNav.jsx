import React from 'react';
import { Activity, LayoutDashboard, Video, Map, Filter, Bell } from 'lucide-react';

export default function TopNav({ storeIds, selectedStore, onSelectStore, healthData }) {
  const currentHealth = healthData?.stores?.find(s => s.store_id === selectedStore);
  const statusColor = currentHealth?.status === 'OK' ? 'var(--color-success)' : 'var(--color-error)';

  return (
    <div className="topnav-container">
      {/* Logo & Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{ 
          width: '32px', height: '32px', borderRadius: '8px', 
          background: 'linear-gradient(135deg, var(--color-primary), var(--color-secondary))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: 'var(--glow-primary)'
        }}>
          <Activity size={18} color="white" />
        </div>
        <h2 style={{ fontSize: '1.2rem', margin: 0 }}>Spatial IQ</h2>
      </div>

      {/* Navigation Links */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, justifyContent: 'center' }}>
        <MenuItem icon={<LayoutDashboard size={18} />} label="Overview" active />
        <MenuItem icon={<Video size={18} />} label="Spatial Feeds" />
        <MenuItem icon={<Map size={18} />} label="Heatmaps" />
        <MenuItem icon={<Filter size={18} />} label="Funnels" />
        <MenuItem icon={<Bell size={18} />} label="Anomalies" />
      </div>

      {/* Controls & Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', textTransform: 'uppercase', letterSpacing: '1px' }}>
            Store
          </span>
          <select 
            value={selectedStore} 
            onChange={(e) => onSelectStore(e.target.value)}
            style={{
              padding: '8px 16px', borderRadius: '12px',
              background: 'rgba(255,255,255,0.05)', border: 'var(--border-glass)',
              color: 'white', fontFamily: 'var(--font-sans)', outline: 'none',
              cursor: 'pointer', minWidth: '160px'
            }}
          >
            {storeIds.map(id => (
              <option key={id} value={id} style={{ background: '#0a0f1e' }}>{id}</option>
            ))}
          </select>
        </div>
        
        {currentHealth && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', background: 'rgba(255,255,255,0.02)', borderRadius: '12px', border: 'var(--border-glass)' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: statusColor, boxShadow: `0 0 10px ${statusColor}` }} />
            <span style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--color-text-secondary)' }}>{currentHealth.status}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function MenuItem({ icon, label, active }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px',
      borderRadius: '12px', cursor: 'pointer',
      background: active ? 'linear-gradient(180deg, rgba(255,255,255,0.1), transparent)' : 'transparent',
      borderBottom: active ? '2px solid var(--color-primary)' : '2px solid transparent',
      color: active ? 'white' : 'var(--color-text-secondary)',
      transition: 'all 0.2s ease'
    }}>
      {icon}
      <span style={{ fontSize: '0.9rem', fontWeight: 500 }}>{label}</span>
    </div>
  );
}
