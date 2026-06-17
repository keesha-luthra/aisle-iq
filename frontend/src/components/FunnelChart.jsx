import React from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js';
import { Bar } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend
);

export default function FunnelChart({ data }) {
  const stages = data?.stages || {};
  const vals = [
    stages.entry_count || 0,
    stages.zone_visit_count || 0,
    stages.billing_queue_count || 0,
    stages.purchase_count || 0
  ];
  
  const chartData = {
    labels: ['Entry', 'Zone Visit', 'Billing Queue', 'Purchase'],
    datasets: [
      {
        label: 'Visitors',
        data: vals,
        backgroundColor: [
          'rgba(138, 92, 255, 0.8)',
          'rgba(0, 229, 255, 0.8)',
          'rgba(255, 79, 216, 0.8)',
          'rgba(0, 255, 157, 0.8)'
        ],
        borderRadius: 4,
      }
    ]
  };

  const options = {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.05)' },
        ticks: { color: '#94A3B8' }
      },
      y: {
        grid: { display: false },
        ticks: { color: '#94A3B8' }
      }
    }
  };

  const hasData = vals.some(v => v > 0);

  return (
    <div className="w-full h-[250px]">
      {hasData ? (
        <Bar data={chartData} options={options} />
      ) : (
        <div className="flex items-center justify-center h-full text-gray-500 text-sm">
          No funnel data available
        </div>
      )}
    </div>
  );
}
