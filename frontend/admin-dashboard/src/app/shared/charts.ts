import { Provider } from '@angular/core';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';

// ng2-charts <= 5 applied these dataset color defaults automatically (NgChartsConfiguration.generateColors);
// v10 dropped them, so they are restated here to keep chart rendering unchanged.
const baseColors: number[][] = [
  [255, 99, 132],
  [54, 162, 235],
  [255, 206, 86],
  [231, 233, 237],
  [75, 192, 192],
  [151, 187, 205],
  [220, 220, 220],
  [247, 70, 74],
  [70, 191, 189],
  [253, 180, 92],
  [148, 159, 177],
  [77, 83, 96],
];
const randomChannel = () => Math.floor(Math.random() * 256);
const rgba = (index: number, alpha: number) =>
  `rgba(${(baseColors[index] ?? [randomChannel(), randomChannel(), randomChannel()]).concat(alpha).join(',')})`;

type Ctx = { datasetIndex: number; dataIndex: number };
const line = {
  backgroundColor: (c: Ctx) => rgba(c.datasetIndex, 0.4),
  borderColor: (c: Ctx) => rgba(c.datasetIndex, 1),
  pointBackgroundColor: (c: Ctx) => rgba(c.datasetIndex, 1),
  pointBorderColor: '#fff',
};
const doughnut = { backgroundColor: (c: Ctx) => rgba(c.dataIndex, 0.6), borderColor: '#fff' };

const chartDefaults = {
  plugins: { colors: { enabled: false } },
  datasets: {
    line,
    radar: line,
    bar: {
      backgroundColor: (c: Ctx) => rgba(c.datasetIndex, 0.6),
      borderColor: (c: Ctx) => rgba(c.datasetIndex, 1),
    },
    doughnut,
    pie: doughnut,
    polarArea: {
      backgroundColor: (c: Ctx) => rgba(c.dataIndex, 0.6),
      borderColor: (c: Ctx) => rgba(c.dataIndex, 1),
    },
  },
};

export function provideAppCharts(): Provider {
  return provideCharts(withDefaultRegisterables(), { defaults: chartDefaults as never });
}
