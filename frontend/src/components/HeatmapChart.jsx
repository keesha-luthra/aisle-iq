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

export default function HeatmapChart({ data }) {
  const zones = data?.zones || [];
  
  const chartData = {
    labels: zones.map(z => z.zone_id),
    datasets: [
      {
        label: 'Zone Score',
        data: zones.map(z => z.normalised_score),
        backgroundColor: 'rgba(138, 92, 255, 0.6)',
        borderColor: '#8A5CFF',
        borderWidth: 1,
        borderRadius: 4,
      }
    ]
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
    },
    scales: {
      y: {
        grid: { color: 'rgba(255,255,255,0.05)' },
        ticks: { color: '#94A3B8' }
      },
      x: {
        grid: { display: false },
        ticks: { color: '#94A3B8' }
      }
    }
  };

  return (
    <div className="w-full h-[250px]">
      {zones.length > 0 ? (
        <Bar data={chartData} options={options} />
      ) : (
        <div className="flex items-center justify-center h-full text-gray-500 text-sm">
          No heatmap data available
        </div>
      )}
    </div>
  );
}
